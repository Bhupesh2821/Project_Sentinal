"""Explicit licensed photo downloads for the user's reported item categories."""
from pathlib import Path
import hashlib,json,sys,time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import requests
from sentinal.config import ROOT
DATA=ROOT/'data/v021-items'
ITEMS=[('scissors_household','Standard household scissors.jpg','CC BY-SA 4.0'),('scissors_pair','2scissors.jpg','CC BY 1.0'),('spoon_small','Small spoon.jpg','CC BY-SA 4.0'),('spoon_chopsticks','Spoon and chopsticks.jpg','CC BY 2.0'),('cleaver','Foster Cleaver.jpg','CC BY-SA 4.0'),('utility_blade','Utility knife.jpg','CC BY-SA 2.5'),('toy_gun','Toy gun.jpg','CC BY-SA 4.0')]
SESSION=requests.Session();SESSION.headers['User-Agent']='SENTINAL local defensive vision evaluation/0.2.1'

def fetch(url,**kwargs):
    for attempt in range(3):
        try:
            response=SESSION.get(url,timeout=25,**kwargs);response.raise_for_status();return response
        except requests.RequestException:
            if attempt==2:raise
            time.sleep(.5*(attempt+1))

def main():
    DATA.mkdir(parents=True,exist_ok=True)
    for key,title,license in ITEMS:
        target=DATA/(key+'.jpg');sidecar=target.with_suffix('.source.json')
        if target.is_file() and sidecar.is_file():continue
        try:
            result=fetch('https://commons.wikimedia.org/w/api.php',params={'action':'query','format':'json','titles':'File:'+title,'prop':'imageinfo','iiprop':'url|extmetadata','iiurlwidth':1280}).json()
            info=next(iter(result['query']['pages'].values()))['imageinfo'][0]
            url=info.get('thumburl',info['url']).split('?')[0];data=fetch(url).content
            if len(data)>8*1024**2:raise ValueError('Photo exceeds bounded evaluation fixture size')
            target.write_bytes(data)
            record={'title':'File:'+title,'source_url':info['descriptionurl'],'download_url':url,'chosen_license':license,'source_metadata':info,'sha256':hashlib.sha256(data).hexdigest(),'scope':'Selected development photo of reported category, no independent train/test separation claim; no user camera media'}
            sidecar.write_text(json.dumps(record,indent=2)+'\n');print(key,len(data),flush=True)
        except Exception as exc:print(key,'FAILED',type(exc).__name__,str(exc)[:100],flush=True)
if __name__=='__main__':main()
