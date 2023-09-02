import yt_dlp

urls = ['']

ydl_opts = {
    'format': 'm4a/bestaudio/best',
    'ignoreerrors': True,
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'm4a',
    }] #{ 'key': 'FFmpegSplitChapters' }
}

#print(yt_dlp.YoutubeDL.__doc__)

def download():
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        error_code = ydl.download(urls)

download()
