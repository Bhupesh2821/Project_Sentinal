"""One-command local website/dashboard setup and service. No automatic capture."""
import argparse,getpass,secrets,sys,threading,webbrowser
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sentinal.connected.store import Store
from sentinal.connected.edge import EdgeConfig
from sentinal.connected.server import build_server


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--allow-local-preview',action='store_true',help='Authorize RAM-only local previews; edge delivery needs its own explicit preview option')
    args=parser.parse_args()
    store=Store(ROOT/'recordings/connected/server.sqlite3')
    try:
        if not store.users('default'):
            print('Create your private local SENTINAL administrator account. This is separate from Base44 sign-in.')
            username=input('Username [bhupesh]: ').strip() or 'bhupesh'
            password=getpass.getpass('Password (12+ characters): ')
            if password!=getpass.getpass('Confirm password: '):raise ValueError('Passwords did not match')
            store.create_user(username,password,'admin','default')
            print('Local administrator created. No demonstration incidents or cameras were added.')
        credential_file=ROOT/'config/connected/edge-credentials.json'
        if not credential_file.exists():
            device_id='edge-'+secrets.token_hex(8);secret=secrets.token_urlsafe(48)
            store.register_device(device_id,'SENTINAL local edge',secret,'default')
            EdgeConfig(f'http://127.0.0.1:{args.port}',device_id,secret,allow_loopback_http=True).save(credential_file)
            print('Local edge paired. In the desktop app, load the paired file and explicitly enable outbound metadata.')
        server=build_server(store,'127.0.0.1',args.port,allow_local_preview=args.allow_local_preview)
        url=f'http://127.0.0.1:{server.server_port}'
        print('Public project website: '+url)
        print('Private dashboard: '+url+'/app')
        print('Camera capture and metadata delivery are off until separately enabled. Press Control+C to stop this service.',flush=True)
        if not args.no_browser:threading.Timer(.5,lambda:webbrowser.open(url+'/app')).start()
        try:server.serve_forever(poll_interval=.2)
        except KeyboardInterrupt:pass
        finally:server.server_close()
    finally:store.close()
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,OSError,EOFError) as exc:
        print('Command center could not start: '+str(exc),file=sys.stderr);raise SystemExit(2)
