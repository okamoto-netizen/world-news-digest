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
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript = next(iter(transcript_list))
        fetched = transcript.fetch()
        lines = [item["text"] for item in fetched if item["start"] <= 360.0]
        full_text = " ".join(lines).strip()
        return full_text[:4500]
    except Exception:
        return None


def translate_long_text(text):
    if not text:
        return ""
    chunks = [text[i:i + 1500] for i in range(0, len(text), 1500)]
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
    communicate = edge_tts.Communicate(script_text, VOICE, rate="+15%")
    await communicate.save(output_path)


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
                maxResults=10
            ).execute()

            selected_item = None
            raw_text = None

            for item in res.get("items", []):
                if item["snippet"].get("liveBroadcastContent") != "none":
                    continue
                vid = item["id"]["videoId"]
                text = fetch_full_transcript(vid)
                if text and len(text) >= 400:
                    selected_item = item
                    raw_text = text
                    break

            if not selected_item or not raw_text:
                print(f"十分な字幕付きの動画なし（スキップ）: {label}")
                continue

            vid = selected_item["id"]["videoId"]
            title_orig = selected_item["snippet"]["title"]
            title_ja = translate_long_text(title_orig)
            body_ja = translate_long_text(raw_text)

            script = f"{station_display}のニュースです。{title_ja}。\n{body_ja}"

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
            print(f"詳細ニュース生成完了 ({len(body_ja)}文字): {label}")

        except Exception as e:
            print(f"スキップ ({label}): {e}")

    if not news_items:
        print("ニュースが取得できませんでした。")
        return

    with open("player.html", "r", encoding="utf-8") as f:
        template = f.read()

    items_json = json.dumps(news_items, ensure_ascii=False)
    html_content = template.replace("__NEWS_DATA__", items_json).replace("__TODAY_STR__", today_str)

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_content)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"【詳細解説版・同時再生】朝のワールドニュース ({today_str})"
    msg["From"] = EMAIL_USER
    msg["To"] = EMAIL_USER

    body_lines = [
        f"<h2>{today_str} 世界の朝刊（詳細ニュース・同時再生版）</h2>",
        "<p>ショート動画を除外し、各局の本編ニュース（最大約6分間の内容）を日本語翻訳・音声化しました。</p>",
        f'<p style="margin: 20px 0;"><a href="{PLAYER_URL}" style="background-color: #d32f2f; color: white; padding: 14px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;">▶ 映像＋日本語音声 同時再生プレイヤーを開く</a></p>',
        "<h3>本日のラインナップ</h3>",
        f"<ul>{''.join(program_list_html)}</ul>"
    ]
    email_html = "<html><body style='font-family: sans-serif; line-height: 1.6;'>" + "".join(body_lines) + "</body></html>"
    msg.attach(MIMEText(email_html, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_USER, EMAIL_PASS)
        server.send_message(msg)

    print("詳細解説版の生成とメール送信が完了しました！")


if __name__ == "__main__":
    main()
