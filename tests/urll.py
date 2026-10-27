import urllib.request,ssl
ctx=ssl.create_default_context()
ctx.check_hostname=False
ctx.verify_mode=ssl.CERT_NONE
url='https://tabs.ultimate-guitar.com/tab/print?app_utm_campaign=Export2pdfDownload&flats=0&font_size=0&id=63352&is_ukulele=0&simplified=0&transpose=0'
req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:158.0) Gecko/20100101 Firefox/158.0'})
try:
    r=urllib.request.urlopen(req,timeout=30,context=ctx)
    data=r.read()
    print(r.status, len(data))
    print(data[:150])
except Exception as e:
    print(e)
