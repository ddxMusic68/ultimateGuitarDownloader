import requests
url='https://tabs.ultimate-guitar.com/tab/print?app_utm_campaign=Export2pdfDownload&flats=0&font_size=0&id=63352&is_ukulele=0&simplified=0&transpose=0'
headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:158.0) Gecko/20100101 Firefox/158.0','Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8','Referer':'https://www.ultimate-guitar.com/'}
s=requests.Session()
s.headers.update(headers)
try:
    s.get('https://www.ultimate-guitar.com/', timeout=15, verify=False)
    r=s.get(url,timeout=90,verify=False)
    print(r.status_code)
    print(r.text[:200])
except Exception as e:
    print(e)
