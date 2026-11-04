"""Measured warm model+association calls, separate from camera/UI throughput."""
from pathlib import Path
from dataclasses import replace
import argparse,json,platform,sys,time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import cv2,numpy as np,psutil,torch
from sentinal.config import ROOT,AppConfig
from sentinal.vision.detector import YOLODetector
from sentinal.vision.specialized import SpecializedSuite
from tools.evaluate_detection_matrix_v021 import BASE_MODELS


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device',choices=('cpu','mps'),default='mps')
    parser.add_argument('--samples',type=int,default=12)
    args=parser.parse_args()
    if not 4<=args.samples<=100:raise ValueError('Use4–100 measured samples')
    if args.device=='mps' and not torch.backends.mps.is_available():raise RuntimeError('MPS unavailable; explicitly choose cpu')
    frame=cv2.imread(str(ROOT/'data/v021-items/cleaver.jpg'))
    if frame is None:raise RuntimeError('Licensed benchmark source absent')
    frame=cv2.resize(frame,(640,480),interpolation=cv2.INTER_AREA)
    process=psutil.Process();rows=[]
    for model_path in (*BASE_MODELS,'selected-weapons+fire_smoke'):
        is_suite=model_path.startswith('selected-')
        engine=SpecializedSuite(device=args.device,enabled=('weapons','fire_smoke'),confidence=.25) if is_suite else YOLODetector(AppConfig(model_path=model_path,device=args.device))
        for size in (320,640,960):
            if is_suite:engine.configure(image_size=size)
            else:engine.config=replace(engine.config,image_size=size)
            started=time.perf_counter();engine.infer(frame);first=(time.perf_counter()-started)*1000
            for _ in range(3):engine.infer(frame)
            samples=[]
            for index in range(args.samples):
                started=time.perf_counter();engine.infer(frame);samples.append((time.perf_counter()-started)*1000)
            row={'models':model_path,'requested_device':args.device,'actual_devices':{k:v.get('device') for k,v in engine.health.items() if v.get('status')=='active'} if is_suite else {'ordinary':engine.device},'input_size':size,'source_shape':[480,640,3],'first_call_including_shape_warmup_ms':first,'warmup_calls_excluded':3,'samples':args.samples,'mean_ms':float(np.mean(samples)),'p95_ms':float(np.percentile(samples,95)),'throughput_fps_excluding_camera_ui':1000/float(np.mean(samples)),'process_rss_mb':process.memory_info().rss/1024**2}
            if args.device=='mps':row.update(mps_tensor_allocated_mb=torch.mps.current_allocated_memory()/1024**2,mps_driver_allocated_mb=torch.mps.driver_allocated_memory()/1024**2)
            rows.append(row);print(model_path,size,round(row['mean_ms'],2),'ms',flush=True)
        if is_suite:engine.close()
        del engine
        if args.device=='mps':torch.mps.empty_cache()
    report={'scope':'One licensed realcleaver photo downsampled preserving4:3 to640x480; repeatedwarm model+ByteTrackcalls, no accuracy or liveend-to-end FPSclaim; actualselecteddevices reported. Firstcall includes loadingonlyfirstsize, threeadditionalwarmups excluded. Sequentialmodels, no intentional concurrent GPUtest; other hostload notcontrolled.','platform':platform.platform(),'torch':torch.__version__,'ram_gb':psutil.virtual_memory().total/1024**3,'rows':rows}
    target=ROOT/'docs/evidence/v021-2026-11-02'/('detection-warm-benchmark-'+args.device+'.json');target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(report,indent=2)+'\n')
if __name__=='__main__':main()
