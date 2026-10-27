import requests, json
from bs4 import BeautifulSoup
url='https://tabs.ultimate-guitar.com/tab/print?app_utm_campaign=Export2pdfDownload&flats=0&font_size=0&id=63352&is_ukulele=0&simplified=0&transpose=0'
headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:158.0) Gecko/20100101 Firefox/158.0'}
r=requests.get(url,headers=headers,timeout=30,verify=False)
print(r.status_code)
soup=BeautifulSoup(r.text,'html.parser')
store=soup.select_one('.js-store[data-content]')
print('store:', store is not None)
if store:
    data=json.loads(store['data-content'])
    print(list(data.keys())[:5])
else:
    # look for other patterns
    for s in soup.find_all('script'):
        if 'tab' in s.text.lower() and len(s.text)>100 and len(s.text)<5000:
            print('---SCRIPT---')
            print(s.text[:300])
            break
