import os
import asyncio
import subprocess
import smtplib
import requests
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
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_REPOSITORY = os.environ["GITHUB_REPOSITORY"]

# NHKワールドニュース相当の主要放送局（計10局）
CHANNELS = {
    "01_BBC_News_英国": "UC16niRr50-MSBwiO3YDb3RA",
    "02_ABC_News_米国": "UCBi2mrWuNuyYy4gbM6fU18Q",
    "03_Al_Jazeera_中東": "UCNye-wNBqNL5ZzHSJj3l8Bg",
    "04_DW_News_ドイツ": "UCknLrEdhRCp1aegoMqRaCZg",
    "05_France24_フランス": "UCQfwfsi5VrQ8yKZ-UWmAEFg",
    "06_RTVE_スペイン": "UC7QZIf0AyafaWXxHTiuMSZQ",
    "07_KBS_News_韓国": "UCcQTRi69dsVYHN3exePtZ1A",
    "08_CGTN_中国": "UCgrNz-aEg5VUq4P46F382MA",
    "09_CNA_アジア": "UC83jt4dlz1Gjl58fzQrrKZg",
    "10_ABC_Australia_豪州": "UCVgO39Bk5sMo66-6o6Spn6Q",
}

VOICE = "ja-JP-NanamiNeural"

def get_transcript_and_duration(video_id):
    """字幕テキストを取得する"""
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript = next(iter(transcript_list))
        fetched = transcript.fetch()
        selected_lines = []
        for item in fetched:
            if item["start"] > 75.0:
                break
            selected_lines.append(item["text"])
        full_text = " ".join(selected_lines)
        return full_text[:1000]
    except Exception:
        return None

def translate_to_japanese(text):
    try:
        return GoogleTranslator(source="auto", target="ja").translate(text)
    except Exception:
        return ""

async def generate_tts(text, out_mp3):
    communicate = edge_tts.Communicate(text, VOICE, rate="+12%")
    await communicate.save(out_mp3)

def get_audio_duration(filepath):
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", filepath
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, text=True)
    try:
        return float(res.stdout.strip())
    except Exception:
        return 60.0

def download_video_clip(video_id, out_mp4, max_sec):
    """YouTubeから映像をダウンロードし、日本語音声の長さに合わせて切り出す"""
    url = f"https://www.youtube.com/watch?v={video_id}"
    raw_file = f"raw_{video_id}.mp4"
    cmd = [
        "yt-dlp",
        "-f", "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best",
        "--download-sections", f"*0:00-{int(max_sec) + 5}",
        "--force-keyframes-at-cuts",
        "-o", raw_file,
        url
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.path.exists(raw_file):
        os.rename(raw_file, out_mp4)
        return True
    return False

def dub_video(raw_mp4, ja_mp3, final_mp4, duration):
    """元映像の音声を15%に下げ、日本語音声を被せて統一フォーマット(1280x720)で出力する"""
    cmd = [
        "ffmpeg", "-y",
        "-i", raw_mp4,
        "-i", ja_mp3,
        "-filter_complex",
        "[0:v]scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,fps=30[v];"
        "[0:a]volume=0.15[orig_a];"
        "[1:a]volume=1.3[ja_a];"
        "[orig_a][ja_a]amix=inputs=2:duration=shortest[a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
        "-c:a", "aac", "-b:a", "128k",
        "-t", str(duration),
        final_mp4
    ]
    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return res.returncode == 0 and os.path.exists(final_mp4)

def upload_to_github_release(tag_name, title, file_paths):
    """完成したMP4動画をGitHub Releasesに無料アップロードして直リンクを取得する"""
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    api_url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases"

    requests.delete(f"{api_url}/tags/{tag_name}", headers=headers)

    res = requests.post(api_url, headers=headers, json={
        "tag_name": tag_name,
        "name": title,
        "body": "本日の日本語吹き替え国際ニュース映像（自動生成）",
        "draft": False,
        "prerelease": False
    })
    release_data = res.json()
    upload_url = release_data["upload_url"].split("{")[0]

    download_links = {}
    for fp in file_paths:
        fname = os.path.basename(fp)
        with open(fp, "rb") as f:
            up_res = requests.post(
                f"{upload_url}?name={fname}",
                headers={
                    "Authorization": f"token {GITHUB_TOKEN}",
                    "Content-Type": "video/mp4"
                },
                data=f.read()
            )
            if up_res.status_code in (200, 201):
                download_links[fname] = up_res.json()["browser_download_url"]
    return download_links

def main():
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    jst = timezone(timedelta(hours=9))
    today_str = datetime.now(jst).strftime("%Y年%m月%d日")
    tag_date = datetime.now(jst).strftime("%Y%m%d")

    dubbed_files = []
    program_notes = []

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

            for item in res.get("items", []):
                if item["snippet"].get("liveBroadcastContent") != "none":
                    continue
                vid = item["id"]["videoId"]
                raw_text = get_transcript_and_duration(vid)
                if not raw_text or len(raw_text) < 150:
                    continue

                title_orig = item["snippet"]["title"]
                title_ja = translate_to_japanese(title_orig)
                body_ja = translate_to_japanese(raw_text)
                if not body_ja:
                    continue

                narration = f"{station_display}のニュースです。{title_ja}。{body_ja}"
                ja_mp3 = f"ja_{label}.mp3"
                asyncio.run(generate_tts(narration, ja_mp3))
                dur = get_audio_duration(ja_mp3)

                raw_mp4 = f"clip_{label}.mp4"
                final_mp4 = f"{label}.mp4"

                if download_video_clip(vid, raw_mp4, dur):
                    if dub_video(raw_mp4, ja_mp3, final_mp4, dur):
                        dubbed_files.append(final_mp4)
                        program_notes.append(f"・{station_display}: {title_ja}")
                        print(f"吹き替え動画完成: {label}")
                        break
        except Exception as e:
            print(f"スキップ ({label}): {e}")

    if not dubbed_files:
        print("動画が1本も生成できませんでした。")
        return

    full_program_mp4 = f"00_NHK風ワールドニュース連続再生_{tag_date}.mp4"
    with open("concat_list.txt", "w", encoding="utf-8") as f:
        for df in dubbed_files:
            f.write(f"file '{df}'\n")

    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", "concat_list.txt", "-c", "copy", full_program_mp4
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    upload_targets = []
    if os.path.exists(full_program_mp4):
        upload_targets.append(full_program_mp4)
    upload_targets.extend(dubbed_files)

    links = upload_to_github_release(
        f"news-{tag_date}",
        f"世界の朝刊 日本語吹き替え映像 ({today_str})",
        upload_targets
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"【映像＋日本語吹き替え】朝のワールドニュース ({today_str})"
    msg["From"] = EMAIL_USER
    msg["To"] = EMAIL_USER

    full_link = links.get(full_program_mp4, "")
    individual_html = "".join([
        f"<li><a href='{url}'>{fname}</a></li>"
        for fname, url in links.items() if fname != full_program_mp4
    ])
    notes_html = "<br>".join(program_notes)

    html_body = f"""
    <html>
      <body style="font-family: sans-serif; line-height: 1.6;">
        <h2>{today_str} 世界の朝刊（日本語吹き替え映像版）</h2>
        <p>元映像の現地音声を下げ、日本語AIアナウンサー音声を合成したニュース番組です。</p>
        <p style="margin: 20px 0;">
          <a href="{full_link}" style="background-color: #d32f2f; color: white; padding: 14px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;">
            ▶ 全放送局まとめ映像を再生・保存する（MP4）
          </a>
        </p>
        <h3>本日のラインナップ</h3>
        <p>{notes_html}</p>
        <h3>放送局別の個別動画</h3>
        <ul>{individual_html}</ul>
      </body>
    </html>
    """
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_USER, EMAIL_PASS)
        server.send_message(msg)

    print("映像＋日本語吹き替えニュースの配信が完了しました！")

if __name__ == "__main__":
    main()
