"""Download a small disclosed licensed screening set, never user camera media."""
import hashlib,json,time
from pathlib import Path
import requests
from sentinal.config import ROOT
ROOT_DATA=ROOT/'data/v02-evaluation'
SEARCHES=[('fire','forest fire flames filetype:bitmap'),('smoke','wildfire smoke plume filetype:bitmap'),('steam','steam kettle filetype:bitmap'),('fog','fog landscape filetype:bitmap'),('bright_light','bright street lights filetype:bitmap'),('reflection','orange reflection water filetype:bitmap'),('dust','dust cloud filetype:bitmap'),('rifle','M16 rifle filetype:bitmap'),('knife','kitchen knife filetype:bitmap')]
SESSION=requests.Session()
SESSION.headers['User-Agent']='SENTINAL/0.2 local noncommercial vision research'

def get(url,**kwargs):
    error=None
    for attempt in range(3):
        try:
            r=SESSION.get(url,timeout=25,**kwargs);r.raise_for_status()
            return r
        except Exception as exc:
            error=exc;time.sleep(.5*(attempt+1))
    raise error

def run():
    ROOT_DATA.mkdir(parents=True,exist_ok=True)
    records=[]
    for key,query in SEARCHES:
        if (ROOT_DATA/(key+'.source.json')).exists():
            print(key,'already downloaded',flush=True);continue
        try:
            response=get('https://commons.wikimedia.org/w/api.php',params={'action':'query','format':'json','generator':'search','gsrsearch':query,'gsrnamespace':6,'gsrlimit':4,'prop':'imageinfo','iiprop':'url|extmetadata','iiurlwidth':1200}).json()
            pages=sorted(response.get('query',{}).get('pages',{}).values(),key=lambda p:p.get('index',100))
            for page in pages:
                info=page.get('imageinfo',[{}])[0];meta=info.get('extmetadata',{})
                license=meta.get('LicenseShortName',{}).get('value','')
                if license not in {'Public domain','CC0','CC BY 4.0','CC BY-SA 4.0','CC BY 3.0','CC BY-SA 3.0','CC BY 2.0','CC BY-SA 2.0'}:continue
                url=info.get('thumburl',info['url']).split('?')[0]
                r=get(url)
                (ROOT_DATA/(key+'.jpg')).write_bytes(r.content)
                record={'key':key,'title':page['title'],'license':license,'source':info,'sha256':hashlib.sha256(r.content).hexdigest(),'download_url':url}
                (ROOT_DATA/(key+'.source.json')).write_text(json.dumps(record,indent=2))
                records.append(record);print(key,page['title'],license,len(r.content),flush=True);break
            else:print(key,'NO ACCEPTED LICENSED RESULT',flush=True)
        except Exception as exc:print(key,type(exc).__name__,str(exc)[:100],flush=True)
    return records

if __name__=='__main__':run()
