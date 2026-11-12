import os
import asyncio
import smtplib
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication

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

def fetch_transcript_text(video_id):
    """動画の冒頭約90秒分の字幕テキストを取得して映像の進行と合わせる"""
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

def main():
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    jst = timezone(timedelta(hours=9))
    today_str = datetime.now(jst).strftime("%Y年%m月%d日")

    attached_mp3s = []
    program_list_html = []
    all_scripts = []

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
            url = f"https://www.youtube.com/watch?v={vid}"

            raw_text = fetch_transcript_text(vid)
            if raw_text and len(raw_text) > 100:
                body_ja = translate_to_japanese(raw_text)
                script = f"{station_display}のニュースです。{title_ja}。{body_ja}"
            else:
                script = f"{station_display}のヘッドラインです。{title_ja}。"

            mp3_filename = f"{label}.mp3"
            asyncio.run(generate_audio(script, mp3_filename))
            attached_mp3s.append(mp3_filename)
            all_scripts.append(f"【{label}】\n{script}")

            program_list_html.append(
                f"<li style='margin-bottom: 10px;'>"
                f"<strong>{label}</strong>: {title_ja}<br>"
                f"👉 <a href='{url}'>このニュースの映像を開く</a>（添付の <b>{mp3_filename}</b> と同時再生）"
                f"</li>"
            )
            print(f"生成完了: {label}")

        except Exception as e:
            print(f"スキップ ({label}): {e}")

    if not attached_mp3s:
        print("ニュースが取得できませんでした。")
        return

    msg = MIMEMultipart()
    msg["Subject"] = f"【局別同期版】朝のワールドニュース ({today_str})"
    msg["From"] = EMAIL_USER
    msg["To"] = EMAIL_USER

    html_body = f"""
    <html>
      <body style="font-family: sans-serif; line-height: 1.6;">
        <h2>{today_str} 世界の朝刊（局別同期・日本語音声版）</h2>
        <p>映像と音声のズレを防ぐため、<strong>放送局ごとに個別のMP3音声</strong>を添付しています。<br>
        各ニュースの「映像を開く」と同時に、同じ番号のMP3ファイルを再生してください。</p>
        <ul>{''.join(program_list_html)}</ul>
        <hr>
        <h3>日本語読み上げ原稿一覧</h3>
        <pre style="white-space: pre-wrap; font-family: sans-serif; background: #f5f5f5; padding: 12px; border-radius: 6px;">{chr(10)+chr(10).join(all_scripts)}</pre>
      </body>
    </html>
    """
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    for mp3_file in attached_mp3s:
        with open(mp3_file, "rb") as f:
            part = MIMEApplication(f.read(), Name=mp3_file)
            part["Content-Disposition"] = f'attachment; filename="{mp3_file}"'
            msg.attach(part)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_USER, EMAIL_PASS)
        server.send_message(msg)

    print("局別同期版の送信が完了しました！")

if __name__ == "__main__":
    main()
