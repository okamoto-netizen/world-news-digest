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

def fetch_full_transcript(video_id):
    """動画全体（最大約6分・4500文字分）の字幕テキストをしっかり取得する"""
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript = next(iter(transcript_list))
        fetched = transcript.fetch()
        # 最初の約360秒（6分間）の字幕をすべて結合
        lines = [item["text"] for item in fetched if item["start"] <= 360.0]
        full_text = " ".join(lines).strip()
        return full_text[:4500]
    except Exception:
        return None

def translate_long_text(text):
    """長文を1,500文字ずつに分割して確実に日本語へ翻訳する"""
    if not text:
        return ""
    chunks = [text[i:i+1500] for i in range(0, len(text), 1500)]
    translated_parts = []
    for chunk in chunks:
        try:
            res = GoogleTranslator(source="auto", target="ja").translate(chunk)
            if res:
                translated_parts.append(res)
        except Exception:
            translated_parts.append(chunk)
    return "".join(translated_parts)

async def generate_audio(script_text, output_path):
    # 情報量が増えるため、聞き取りやすくテンポの良い +15% 速度に設定
    communicate = edge_tts.Communicate(script_text, VOICE, rate="+15%")
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
    .script-box {{ background: #1e1e1e; padding: 14px; border-radius: 8px; font-size: 0.95rem; line-height: 1.7; color: #eee; margin-bottom: 16px; max-height: 220px; overflow-y: auto; }}
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
            # 直近10件から「しっかり字幕（内容）がある本編ニュース」を探す
            res = youtube.search().list(
                part="snippet",
                channelId=channel_id,
                order="date",
                type="video",
                videoDuration="medium",  # 4分〜20分の本編ニュースを優先取得（ショート動画を完全除外）
                maxResults=8
            ).execute()

            items = res.get("items", [])
            # mediumで見つからない局は全長さから再検索
            if not items:
                res = youtube.search().list(
                    part="snippet",
                    channelId=channel_id,
                    order="date",
                    type="video",
                    maxResults=8
                ).execute()
                items = res.get("items", [])

            selected_item = None
            raw_text = None

            for item in items:
                if item["snippet"].get("liveBroadcastContent") != "none":
                    continue
                vid = item["id"]["videoId"]
                text = fetch_full_transcript(vid)
                # 400文字以上のしっかりしたニュース原稿が取れた動画のみ採用
                if text and len(text) >= 400:
                    selected_item = item
                    raw_text = text
                    break

            if not selected_item or not raw_text:
                print(f"十分な字幕付きの動画なし（スキップ）: {label}")
                continue

            vid = selected_item["id"]["videoId"]
