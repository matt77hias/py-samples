import yt_dlp

urls = ['']

ydl_opts = {
	#'cookiesfrombrowser': ('chrome',),
    'format_sort': ['ext:mp4:m4a'],
	'ignoreerrors': True
}

def download():
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        error_code = ydl.download(urls)

download()
