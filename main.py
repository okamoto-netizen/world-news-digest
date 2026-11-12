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

# NHKワールドニュース相当の主要放送局（計10局）
CHANNELS = {
    "イギリス、BBCニュース": "UC16niRr50-MSBwiO3YDb3RA",
    "アメリカ、ABCニュース": "UCBi2mrWuNuyYy4gbM6fU18Q",
    "中東、アルジャジーラ": "UCNye-wNBqNL5ZzHSJj3l8Bg",
    "ドイツ、DWニュース": "UCknLrEdhRCp1aegoMqRaCZg",
    "フランス、フランス24": "UCQfwfsi5VrQ8yKZ-UWmAEFg",
    "スペイン、RTVE": "UC7QZIf0AyafaWXxHTiuMSZQ",
    "韓国、KBSニュース": "UCcQTRi69dsVYHN3exePtZ1A",
    "中国、CGTN": "UCgrNz-aEg5VUq4P46F382MA",
    "アジア、CNA": "UC83jt4dlz1Gjl58fzQrrKZg",
    "オーストラリア、ABCニュース": "UCVgO39Bk5sMo66-6o6Spn6Q",
}

VOICE = "ja-JP-NanamiNeural"

def fetch_transcript_text(video_id):
    """動画の字幕テキストを取得する（失敗してもNoneを返し、動画自体は採用する）"""
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript = next(iter(transcript_list))
        fetched = transcript.fetch()
        full_text = " ".join([item["text"] for item in fetched])
        return full_text[:1200]
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
    file_date = datetime.now(jst).strftime("%Y%m%d")

    video_ids = []
    radio_scripts = [f"おはようございます。{today_str}の、世界の主要ニュースをお伝えします。"]
    program_list_html = []

    for station_name, channel_id in CHANNELS.items():
        try:
            res = youtube.search().list(
                part="snippet",
                channelId=channel_id,
                order="date",
                type="video",
                maxResults=5
            ).execute()

            # ライブ配信以外の最新動画を1本選ぶ
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

            video_ids.append(vid)

            # 字幕が取れれば日本語で詳細読み上げ、取れなくても見出しを読み上げ
            raw_text = fetch_transcript_text(vid)
            if raw_text and len(raw_text) > 100:
                body_ja = translate_to_japanese(raw_text)
                radio_scripts.append(f"続いて、{station_name}のニュースです。{title_ja}。{body_ja}")
            else:
                radio_scripts.append(f"続いて、{station_name}のヘッドラインです。{title_ja}。")

            program_list_html.append(
                f"<li><strong>{station_name}</strong>: {title_ja} "
                f"（<a href='{url}'>個別映像を見る</a>）</li>"
            )
            print(f"取得完了: {station_name}")

        except Exception as e:
            print(f"スキップ ({station_name}): {e}")

    if not video_ids:
        print("動画が取得できませんでした。")
        return

    radio_scripts.append("以上、今朝の世界のニュースをお伝えしました。")
    full_script = "\n\n".join(radio_scripts)

    # 日本語音声MP3を生成
    mp3_filename = f"world_news_{file_date}.mp3"
    asyncio.run(generate_audio(full_script, mp3_filename))

    # YouTube連続再生URLを作成
    playlist_url = f"https://www.youtube.com/watch_videos?video_ids={','.join(video_ids)}"

    # メール作成（HTML本文 + MP3音声ファイル添付）
    msg = MIMEMultipart()
    msg["Subject"] = f"【映像＋日本語音声】朝のワールドニュース ({today_str})"
    msg["From"] = EMAIL_USER
    msg["To"] = EMAIL_USER

    html_body = f"""
    <html>
      <body style="font-family: sans-serif; line-height: 1.6;">
        <h2>{today_str} 世界の朝刊（映像＋日本語音声ガイド）</h2>
        <p>添付の<strong>日本語音声ファイル（{mp3_filename}）</strong>を再生しながら、下の赤いボタンで世界のニュース映像を連続再生できます。</p>
        <p style="margin: 20px 0;">
          <a href="{playlist_url}" style="background-color: #d32f2f; color: white; padding: 14px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;">
            ▶ 全10局のニュース映像をワンクリック連続再生する
          </a>
        </p>
        <h3>本日のラインナップ（日本語訳タイトル）</h3>
        <ul>{''.join(program_list_html)}</ul>
        <hr>
        <h3>日本語読み上げ原稿</h3>
        <pre style="white-space: pre-wrap; font-family: sans-serif; background: #f5f5f5; padding: 12px; border-radius: 6px;">{full_script}</pre>
      </body>
    </html>
    """
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    # MP3ファイルを添付
    with open(mp3_filename, "rb") as f:
        part = MIMEApplication(f.read(), Name=mp3_filename)
        part["Content-Disposition"] = f'attachment; filename="{mp3_filename}"'
        msg.attach(part)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_USER, EMAIL_PASS)
        server.send_message(msg)

    print("映像＋日本語音声メールの送信が完了しました！")

if __name__ == "__main__":
    main()
