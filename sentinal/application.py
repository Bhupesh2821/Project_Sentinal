"""Desktop entry point; importing the vision core does not require Qt."""
import argparse
from dataclasses import replace
import logging
import signal
import sys
from time import perf_counter

from sentinal import __version__
from sentinal.config import load_config


def prepare_runtime():
    """Import vision libraries before a window is visible.

    Python's first heavyweight imports can hold the interpreter lock even from
    a QThread. Moving them to application startup keeps that cold import pause
    out of monitoring interactions. This does not load weights, infer, open a
    camera, or start a monitoring session.
    """
    started = perf_counter()
    import ultralytics
    from ultralytics import YOLO  # loads the lazy model-family Python modules
    from ultralytics.trackers import register_tracker
    import torchvision
    details = {
        "elapsed_s": perf_counter() - started,
        "ultralytics": ultralytics.__version__,
        "torchvision": torchvision.__version__,
        "weights_loaded": False,
        "camera_opened": False,
    }
    logging.getLogger(__name__).info("Vision libraries prepared before window display in %.3fs", details["elapsed_s"])
    return details


def main(argv=None):
    parser = argparse.ArgumentParser(description="SENTINAL MARK-007 · local Vision Core")
    parser.add_argument("--config", help="Path to a JSON settings file")
    parser.add_argument("--device", choices=("auto", "cpu", "mps"), help="Preferred inference device; auto prefers working MPS")
    parser.add_argument("--video", help="Preselect a local video; monitoring still requires Start")
    parser.add_argument("--demo", action="store_true", help="Preselect licensed local demonstration footage and explicit prototype thresholds; Start is still required")
    args = parser.parse_args(argv)
    from PySide6.QtWidgets import QApplication, QMessageBox
    from sentinal.core.logger import configure_logging
    from sentinal.interface.main_window import MainWindow
    from sentinal.interface.themes import STYLESHEET

    app = QApplication(sys.argv[:1])
    app.setApplicationName("SENTINAL")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("Project SENTINAL")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    configure_logging()
    try:
        config = load_config(args.config)
        if args.device:
            config = replace(config, device=args.device)
    except Exception as exc:
        logging.getLogger(__name__).exception("Could not load configuration")
        QMessageBox.critical(None, "SENTINAL · Settings error", f"Cannot load settings: {exc}\n\nCorrect the configuration file and reopen SENTINAL.")
        return 2
    try:
        prepare_runtime()
    except Exception:
        logging.getLogger(__name__).exception("Vision libraries could not initialize")
        QMessageBox.critical(None, "SENTINAL · Installation error", "Local vision libraries could not initialize. Run install.command, then reopen SENTINAL. Technical details are in logs/sentinal.log.")
        return 2
    if args.demo and not args.video:
        from sentinal.config import ROOT
        args.video = str(ROOT / 'data/v02-demo/weapon_range_motion.mp4')
    window = MainWindow(config, args.video)
    if args.demo:
        from sentinal.core.v02_settings import V02Settings
        window.hazard_settings = replace(V02Settings(), detectors=('weapons',), confidence=.35, persistence_s=.3, max_gap_s=2.)
        window.hazards_toggle.setChecked(True)
        window.connection_label.setText('DEMO · Possible weapons profile on prerecorded input. Press Start; review every warning. Enable fire/smoke in Operator center for the next source.')
    window.show()
    signal.signal(signal.SIGINT, lambda *_: window.close())
    try:
        return app.exec()
    finally:
        # Also cover system/application Quit paths that bypass closeEvent.
        edge=getattr(window,'_edge_bridge',None)
        if edge is not None:edge.stop()
        window.worker.request_shutdown()
        window.worker.wait()
        if edge is not None:edge.close(timeout=5)
        setup = getattr(window, "_network_dialog", None)
        if setup is not None:
            setup.cancel_setup()
            setup.wait_for_setup()
        importer = getattr(window, "_import_worker", None)
        if importer is not None:
            importer.cancel()
            importer.wait()
        manager = getattr(window, '_camera_manager_dialog', None)
        if manager is not None:
            manager.cancel_setup()
            manager.wait_for_setup()
        incidents = getattr(window, '_incident_worker', None)
        if incidents is not None:
            incidents.request_shutdown()
            incidents.wait()
        wall = getattr(window,'_camera_wall',None)
        if wall is not None:
            wall.worker.request_shutdown();wall.worker.wait()
        window._cleanup_v02()
