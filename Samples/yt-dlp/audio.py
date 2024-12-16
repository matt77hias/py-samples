import yt_dlp

urls = ['']

ydl_opts = {
	#'cookiesfrombrowser': ('firefox',),
    'format': 'm4a/bestaudio/best',
    'ignoreerrors': True,
	'outtmpl': '%(autonumber)02d %(title)s.%(ext)s',
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
