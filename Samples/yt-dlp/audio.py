import yt_dlp

urls = ['']

hidden_files = False

ydl_opts = {
    'format': 'm4a/bestaudio/best',
    'ignoreerrors': hidden_files,
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'm4a',
    }]
}

def download():
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        error_code = ydl.download(urls)

download()
