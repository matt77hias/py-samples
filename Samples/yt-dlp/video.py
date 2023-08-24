import yt_dlp

urls = ['']

hidden_files = False

ydl_opts = {
    'format_sort': ['ext:mp4:m4a'],
	'ignoreerrors': hidden_files
}

def download():
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        error_code = ydl.download(urls)

download()
