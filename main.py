import datetime
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from googleapiclient.discovery import build

# GitHubのSecretsから設定値を読み込む
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS")
TO_EMAIL = EMAIL_USER

# NHKワールドニュース相当の主要放送局チャンネルID
CHANNELS = {
    "BBC News (英国)": "UC16niRr50-MSBwiO3YDb3RA",
    "Al Jazeera English (中東)": "UCNye-wNBqNL5ZzHSJj3l8Bg",
    "DW News (ドイツ)": "UCknLrEdhRCp1aegoMqRaCZg",
    "France 24 English (フランス)": "UCQfwfsi5VrQ8yKZ-UWmAEFg",
    "CNA (シンガポール/アジア)": "UC83jt4dlz1Gjl58fzQrrKZg",
}


def get_latest_video(youtube, channel_id):
    """各チャンネルの最新動画を1件取得"""
    try:
        res = (
            youtube.search()
            .list(
                part="id,snippet",
                channelId=channel_id,
                order="date",
                type="video",
                maxResults=1,
            )
            .execute()
        )
        items = res.get("items", [])
        if items:
            return {
                "id": items[0]["id"]["videoId"],
                "title": items[0]["snippet"]["title"],
            }
    except Exception as e:
        print(f"Error fetching channel {channel_id}: {e}")
    return None


def main():
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    video_ids = []
    video_list_text = ""

    for name, ch_id in CHANNELS.items():
        v = get_latest_video(youtube, ch_id)
        if v:
            video_ids.append(v["id"])
            video_list_text += f"<li><b>{name}</b>: {v['title']}<br><a href='https://www.youtube.com/watch?v={v['id']}'>個別で見る</a></li><br>"

    # YouTube動画を連続再生するワンクリックURL
    continuous_play_url = (
        f"https://www.youtube.com/watch_videos?video_ids={','.join(video_ids)}"
    )

    jst_today = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    date_str = jst_today.strftime("%Y/%m/%d")

    html_content = f"""
    <html>
      <body style="font-family: sans-serif; line-height: 1.6;">
        <h2>🌍 ワールドニュース 毎朝ダイジェスト ({date_str})</h2>
        <p>本日の世界主要ニュースの最新動画がまとまりました。</p>
        <div style="margin: 20px 0;">
          <a href="{continuous_play_url}" style="background-color: #cc0000; color: white; padding: 12px 24px; text-decoration: none; font-size: 16px; border-radius: 5px; font-weight: bold; display: inline-block;">
            ▶ ワンクリックで全番組を連続再生する
          </a>
        </div>
        <hr>
        <h3>本日のラインナップ</h3>
        <ul>
          {video_list_text}
        </ul>
      </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"【朝の国際ニュース】ワンクリック連続再生リスト ({date_str})"
    msg["From"] = EMAIL_USER
    msg["To"] = TO_EMAIL
    msg.attach(MIMEText(html_content, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_USER, EMAIL_PASS)
        server.send_message(msg)

    print("メール送信が完了しました。")


if __name__ == "__main__":
    main()
