import os
import json
import glob
import asyncio
import smtplib
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi
from deep_translator import GoogleTranslator
import edge_tts

YOUTUBE_API_KEY = os.environ["YOUTUBE_API_KEY"]
EMAIL_USER = os.environ["EMAIL_USER"]
EMAIL_PASS = os.environ["EMAIL_PASS"]

CHANNELS = {
    "01_BBC_英国": "UC16niRr50-MSBwiO3YDb3RA",
    "02_ABC_米国": "UCBi2mrWuNuyYy4gbM6fU18Q",
    "03_AlJazeera_中東": "UCNye-wNBqNL5ZzHSJj3l8Bg",
    "04_DW_ドイツ": "UCknLrEdhRCp1aegoMqRaCZg",
    "05_France24_フランス": "UCQfwfsi5VrQ8yKZ-UWmAEFg",
    "06_RTVE_スペイン": "UC7QZIf0AyafaWXxHTiuMSZQ",
    "07_KBS_韓国": "UCcQTRi69dsVYHN3exePtZ1A",
    "08_CGTN_中国": "UCgrNz-aEg5VUq4P46F382MA",
    "09_CNA_アジア": "UC83jt4dlz1Gjl58fzQrrKZg",
    "10_ABC_豪州": "UCVgO39Bk5sMo66-6o6Spn6Q",
}

VOICE = "ja-JP-NanamiNeural"
PLAYER_URL = "https://okamoto-netizen.github.io/world-news-digest/"

def fetch_transcript_text(video_id):
    """動画の冒頭約90秒分の字幕テキストを取得する"""
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript = next(iter(transcript_list))
        fetched = transcript.fetch()
        lines = [item["text"] for item in fetched if item["start"] <= 90.0]
        return " ".join(lines)[:1200]
    except Exception:
        return None

def translate_to_japanese(text):
    try:
        return GoogleTranslator(source="auto", target="ja").translate(text)
    except Exception:
        return text

async def generate_audio(script_text, output_path):
    communicate = edge_tts.Communicate(script_text, VOICE, rate="+10%")
    await communicate.save(output_path)

def build_player_html(today_str, news_items):
    """YouTube映像とMP3音声を同時スタート・連続再生するWebプレイヤーを生成する"""
    items_json = json.dumps(news_items, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>世界の朝刊 同時通訳プレイヤー ({today_str})</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #121212; color: #f5f5f5; margin: 0; padding: 16px; }}
    .container {{ max-width: 820px; margin: 0 auto; }}
    h1 {{ font-size: 1.3rem; margin-bottom: 12px; color: #fff; }}
    .video-box {{ position: relative; width: 100%; padding-top: 56.25%; background: #000; border-radius: 8px; overflow: hidden; }}
    #yt-player {{ position: absolute; top: 0; left: 0; width: 100%; height: 100%; }}
    .controls {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 14px 0; align-items: center; background: #1e1e1e; padding: 12px; border-radius: 8px; }}
    button {{ background: #d32f2f; color: white; border: none; padding: 10px 18px; border-radius: 6px; font-size: 0.95rem; font-weight: bold; cursor: pointer; }}
    button.secondary {{ background: #333; }}
    button:hover {{ opacity: 0.9; }}
    .now-playing {{ font-size: 0.95rem; color: #ff8a80; font-weight: bold; margin-bottom: 8px; }}
    .script-box {{ background: #1e1e1e; padding: 12px; border-radius: 8px; font-size: 0.9rem; line-height: 1.6; color: #ddd; margin-bottom: 16px; max-height: 140px; overflow-y: auto; }}
    .playlist {{ list-style: none; padding: 0; margin: 0; }}
    .playlist li {{ background: #1e1e1e; margin-bottom: 8px; padding: 12px; border-radius: 8px; display: flex; justify-content: space-between; align-items: center; gap: 10px; cursor: pointer; border-left: 4px solid transparent; }}
    .playlist li.active {{ border-left-color: #d32f2f; background: #2a2020; }}
    .station {{ font-size: 0.8rem; color: #aaa; }}
    .title {{ font-size: 0.95rem; font-weight: bold; margin-top: 2px; }}
  </style>
</head>
<body>
<div class="container">
  <h1>🌍 世界の朝刊 NHK風同時通訳プレイヤー ({today_str})</h1>
  <div class="now-playing" id="now-playing">下のボタンまたは番組を選択して再生してください</div>
  <div class="video-box">
    <div id="yt-player"></div>
  </div>
  <div class="controls">
    <button onclick="playIndex(currentIndex)">▶ 映像と日本語音声を同時スタート</button>
    <button class="secondary" onclick="pauseBoth()">⏸ 一時停止</button>
    <button class="secondary" onclick="nextTrack()">⏭ 次の局へ</button>
    <label style="font-size: 0.85rem; margin-left: auto;">
      現地音ボリューム: <input type="range" id="orig-vol" min="0" max="50" value="15" oninput="changeOrigVol(this.value)">
    </label>
  </div>
  <div class="script-box" id="script-box">ここに日本語読み上げ原稿が表示されます。</div>
  <ul class="playlist" id="playlist"></ul>
</div>

<audio id="ja-audio"></audio>
<script src="https://www.youtube.com/iframe_api"></script>
<script>
  const newsItems = {items_json};
  let player = null;
  let currentIndex = 0;
  const audioEl = document.getElementById("ja-audio");
  const playlistEl = document.getElementById("playlist");

  newsItems.forEach((item, idx) => {{
    const li = document.createElement("li");
    li.id = "item-" + idx;
    li.innerHTML = `<div><div class="station">${{item.station}}</div><div class="title">${{item.title}}</div></div><button>▶ 同時再生</button>`;
    li.onclick = () => playIndex(idx);
    playlistEl.appendChild(li);
  }});

  function onYouTubeIframeAPIReady() {{
    if (newsItems.length === 0) return;
    player = new YT.Player("yt-player", {{
      videoId: newsItems[0].videoId,
      playerVars: {{ playsinline: 1, rel: 0 }},
      events: {{
        onReady: () => {{
          player.setVolume(document.getElementById("orig-vol").value);
        }}
      }}
    }});
  }}

  function playIndex(idx) {{
    if (idx < 0 || idx >= newsItems.length) return;
    currentIndex = idx;
    const item = newsItems[idx];

    document.querySelectorAll(".playlist li").forEach(el => el.classList.remove("active"));
    document.getElementById("item-" + idx).classList.add("active");
    document.getElementById("now-playing").textContent = "放送中: " + item.station + " - " + item.title;
    document.getElementById("script-box").textContent = item.script;

    // 映像とMP3音声を同時に頭出し再生
    if (player && player.loadVideoById) {{
      player.loadVideoById({{ videoId: item.videoId, startSeconds: 0 }});
      player.setVolume(document.getElementById("orig-vol").value);
      player.playVideo();
    }}
    audioEl.src = item.audioUrl + "?t=" + Date.now();
    audioEl.currentTime = 0;
    audioEl.play();
  }}

  function pauseBoth() {{
    if (player && player.pauseVideo) player.pauseVideo();
    audioEl.pause();
  }}

  function nextTrack() {{
    if (currentIndex + 1 < newsItems.length) {{
      playIndex(currentIndex + 1);
    }} else {{
      pauseBoth();
      document.getElementById("now-playing").textContent = "本日の全ニュースの放送が終了しました。";
    }}
  }}

  function changeOrigVol(val) {{
    if (player && player.setVolume) player.setVolume(val);
  }}

  // 日本語音声が終わったら自動的に次の局の映像＆音声へ切り替え
  audioEl.addEventListener("ended", () => {{
    nextTrack();
  }});
</script>
</body>
</html>"""

def main():
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    jst = timezone(timedelta(hours=9))
    today_str = datetime.now(jst).strftime("%Y年%m月%d日")

    os.makedirs("audio", exist_ok=True)
    for old_mp3 in glob.glob("audio/*.mp3"):
        os.remove(old_mp3)

    news_items = []
    program_list_html = []

    for label, channel_id in CHANNELS.items():
        station_display = label.split("_", 1)[1].replace("_", " ")
        try:
            res = youtube.search().list(
                part="snippet",
                channelId=channel_id,
                order="date",
                type="video",
                maxResults=5
            ).execute()

            target_item = None
            for item in res.get("items", []):
                if item["snippet"].get("liveBroadcastContent") == "none":
                    target_item = item
                    break

            if not target_item:
                continue

            vid = target_item["id"]["videoId"]
            title_orig = target_item["snippet"]["title"]
            title_ja = translate_to_japanese(title_orig)

            raw_text = fetch_transcript_text(vid)
            if raw_text and len(raw_text) > 100:
                body_ja = translate_to_japanese(raw_text)
                script = f"{station_display}のニュースです。{title_ja}。{body_ja}"
            else:
                script = f"{station_display}のヘッドラインです。{title_ja}。"

            audio_rel_path = f"audio/{label}.mp3"
            asyncio.run(generate_audio(script, audio_rel_path))

            news_items.append({
                "station": station_display,
                "title": title_ja,
                "videoId": vid,
                "audioUrl": audio_rel_path,
                "script": script
            })
            program_list_html.append(f"<li><strong>{station_display}</strong>: {title_ja}</li>")
            print(f"生成完了: {label}")

        except Exception as e:
            print(f"スキップ ({label}): {e}")

    if not news_items:
        print("ニュースが取得できませんでした。")
        return

    # 同時再生プレイヤーHTMLを書き出し
    html_content = build_player_html(today_str, news_items)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_content)

    # メール送信
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"【同時スタート再生対応】朝のワールドニュース ({today_str})"
    msg["From"] = EMAIL_USER
    msg["To"] = EMAIL_USER

    email_html = f"""
    <html>
      <body style="font-family: sans-serif; line-height: 1.6;">
        <h2>{today_str} 世界の朝刊（映像・日本語音声 同時スタート版）</h2>
        <p>下の赤いボタンを押して専用プレイヤーを開き、再生ボタンを押すと<strong>YouTubeのニュース映像と日本語音声が同時にスタート</strong>します。</p>
        <p style="margin: 20px 0;">
          <a href="{PLAYER_URL}" style="background-color: #d32f2f; color: white; padding: 14px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;">
            ▶ 映像＋日本語音声 同時再生プレイヤーを開く
          </a>
        </p>
        <h3>本日のラインナップ</h3>
        <ul>{''.join(program_list_html)}</ul>
      </body>
    </html>
    """
    msg.attach(MIMEText(email_html, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_USER, EMAIL_PASS)
        server.send_message(msg)

    print("同時スタートプレイヤーの生成とメール送信が完了しました！")

if __name__ == "__main__":
    main()
