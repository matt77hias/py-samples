import yt_dlp

urls = ['']

ydl_opts = {
	#'cookiesfrombrowser': ('firefox',),
    'format_sort': ['ext:mp4:m4a'],
    'ignoreerrors': True,
    'outtmpl': '%(autonumber)02d %(title)s.%(ext)s'
}

def download():
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        error_code = ydl.download(urls)

download()
