import os
import time
from datetime import datetime

SOURCE   = os.environ.get("SOURCE",  "/media/Downloads/complete/anime")
DEST     = os.environ.get("DEST",    "/media/Library/anime")
MASTER   = os.environ.get("MASTER",  "/media/masterhardlink/anime")
LOGS_DIR = os.environ.get("LOG_DIR", "/logs")
LOG_FILE = os.path.join(LOGS_DIR, "hardlink.log")
# → LOG_FILE = "/logs/hardlink.log"

INTERVAL_MIN         = 5
LOOKBACK_MIN         = 10
CLEANUP_INTERVAL_MIN = 10


def log(level, message):
    os.makedirs(LOGS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # → ts = "2026-05-29 14:32:07"
    with open(LOG_FILE, "a") as f:
        f.write(f"[{ts}] [{level}] {message}\n")
        # → "[2026-05-29 14:32:07] [INFO] === Starting hardlink job ===\n"


def check_dir(path, label):
    """Create directory if missing, verify writable."""
    # path  = "/media/Library/anime"
    # label = "DEST"
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as e:
        log("ERROR", f"Cannot create {label} ({path}): {e}")
        return False
    if not os.access(path, os.W_OK):
        # os.W_OK is a constant meaning "check write permission"
        # returns True if the process can write to path, False if not
        log("ERROR", f"{label} not writable: {path}")
        return False
    return True


def run_hardlink():
    cutoff  = time.time() - (LOOKBACK_MIN * 60)
    # time.time()      = 1748526727.4  (current Unix timestamp — seconds since Jan 1 1970)
    # LOOKBACK_MIN * 60 = 600          (10 minutes in seconds)
    # cutoff            = 1748526127.4  (timestamp for exactly 10 minutes ago)
    created = skipped = errors = file_count = 0

    log("INFO", "=== Starting hardlink job ===")
    log("INFO", f"SOURCE={SOURCE} | DEST={DEST} | MASTER={MASTER}")

    if not os.path.isdir(SOURCE):
        log("ERROR", f"Source does not exist: {SOURCE}")
        return

    if not check_dir(DEST, "DEST") or not check_dir(MASTER, "MASTER"):
        return

    for root, _, files in os.walk(SOURCE):
        # root  = "/media/Downloads/complete/anime/Attack on Titan/Season 1"
        # _     = []  (subdirs inside Season 1 — empty at leaf level, ignored)
        # files = ["episode01.mkv", "episode02.mkv"]
        for filename in files:
            # filename = "episode01.mkv"
            src = os.path.join(root, filename)
            # src = "/media/Downloads/complete/anime/Attack on Titan/Season 1/episode01.mkv"

            try:
                if os.path.getmtime(src) < cutoff:
                    # getmtime = 1748526000.0, cutoff = 1748526127.4 → file is old, skip
                    continue
            except OSError:
                continue

            file_count += 1
            rel = os.path.relpath(src, SOURCE)
            # rel = "Attack on Titan/Season 1/episode01.mkv"
            dst = os.path.join(DEST, rel)
            # dst = "/media/Library/anime/Attack on Titan/Season 1/episode01.mkv"
            mst = os.path.join(MASTER, rel)
            # mst = "/media/masterhardlink/anime/Attack on Titan/Season 1/episode01.mkv"

            if os.path.exists(dst) and os.path.exists(mst):
                skipped += 1
                continue

            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                # os.path.dirname(dst) = "/media/Library/anime/Attack on Titan/Season 1"
                os.makedirs(os.path.dirname(mst), exist_ok=True)
                # os.path.dirname(mst) = "/media/masterhardlink/anime/Attack on Titan/Season 1"
            except OSError as e:
                log("ERROR", f"mkdir failed for {rel}: {e}")
                errors += 1
                continue

            file_linked = False

            if not os.path.exists(dst):
                try:
                    os.link(src, dst)
                    # ln /media/Downloads/.../episode01.mkv /media/Library/.../episode01.mkv
                    log("SUCCESS", f"LINKED to DEST: {rel}")
                    file_linked = True
                except OSError as e:
                    log("ERROR", f"DEST link failed {rel}: {e}")
                    errors += 1
                    continue  # don't attempt MASTER if DEST failed

            if not os.path.exists(mst):
                try:
                    os.link(src, mst)
                    # ln /media/Downloads/.../episode01.mkv /media/masterhardlink/.../episode01.mkv
                    log("SUCCESS", f"LINKED to MASTER: {rel}")
                    file_linked = True
                except OSError as e:
                    log("ERROR", f"MASTER link failed {rel}: {e}")
                    errors += 1

            if file_linked:
                created += 1

            if file_count % 100 == 0:
                log("INFO", f"Progress: {file_count} files (created={created} errors={errors})")

    log("INFO", f"=== Done: created={created} skipped={skipped} errors={errors} total={file_count} ===")
    print(f"[HARDLINK] created={created} skipped={skipped} errors={errors} total={file_count}")


def run_cleanup():
    removed = errors = 0

    log("INFO", "=== Starting cleanup job ===")

    if not os.path.isdir(SOURCE):
        log("WARNING", f"SOURCE missing, skipping cleanup: {SOURCE}")
        return

    # Build reference set of all relative paths currently in SOURCE
    source_files = set()
    # set() = unordered collection with no duplicates, fast to search
    for root, _, files in os.walk(SOURCE):
        # root  = "/media/Downloads/complete/anime/Attack on Titan/Season 1"
        # _     = []  (subdirs — ignored, we only need file paths)
        # files = ["episode01.mkv", "episode02.mkv"]
        for filename in files:
            # filename = "episode01.mkv"
            rel = os.path.relpath(os.path.join(root, filename), SOURCE)
            # os.path.join(root, filename) = "/media/Downloads/complete/anime/Attack on Titan/Season 1/episode01.mkv"
            # rel                          = "Attack on Titan/Season 1/episode01.mkv"
            source_files.add(rel)
    # → source_files = {
    #     "Attack on Titan/Season 1/episode01.mkv",
    #     "Attack on Titan/Season 1/episode02.mkv",
    #     "One Piece/Season 1/episode01.mkv"
    #   }

    # Guard against empty/failed mount wiping both destinations
    if not source_files:
        log("WARNING", "SOURCE appears empty — skipping cleanup to avoid wiping destinations")
        return

    for label, base in (("DEST", DEST), ("MASTER", MASTER)):
        # 1st iteration: label = "DEST",   base = "/media/Library/anime"
        # 2nd iteration: label = "MASTER", base = "/media/masterhardlink/anime"
        if not os.path.isdir(base):
            log("INFO", f"{label} directory missing, skipping: {base}")
            continue

        # topdown=False → deepest directories visited first, parents last
        # e.g. "/media/Library/anime/Attack on Titan/Season 1"  ← 1st
        #      "/media/Library/anime/Attack on Titan"            ← 2nd
        #      "/media/Library/anime"                            ← last
        for root, dirs, files in os.walk(base, topdown=False):
            # root  = "/media/Library/anime/Attack on Titan/Season 1"  (deepest first)
            # dirs  = []  (subdirs inside Season 1 — empty at leaf level)
            # files = ["episode01.mkv", "episode02.mkv"]
            for filename in files:
                # filename = "episode01.mkv"
                full = os.path.join(root, filename)
                # full = "/media/Library/anime/Attack on Titan/Season 1/episode01.mkv"
                rel  = os.path.relpath(full, base)
                # rel  = "Attack on Titan/Season 1/episode01.mkv"
                if rel not in source_files:
                    # "Naruto/Season 1/ep01.mkv" not in source_files → True → remove
                    # "Attack on Titan/Season 1/episode01.mkv" not in source_files → False → keep
                    try:
                        os.remove(full)
                        log("REMOVED", f"{label}: {rel}")
                        removed += 1
                    except OSError as e:
                        log("ERROR", f"Remove failed {label} {rel}: {e}")
                        errors += 1

            for dirname in dirs:
                dirpath = os.path.join(root, dirname)
                # dirpath = "/media/Library/anime/Attack on Titan/Season 1"
                try:
                    os.rmdir(dirpath)  # removes dir only if empty, raises OSError if not
                except OSError:
                    pass

    log("INFO", f"=== Cleanup done: removed={removed} errors={errors} ===")
    print(f"[CLEANUP] removed={removed} errors={errors}")


if __name__ == "__main__":
    print(f"[HARDLINK] Service started — interval={INTERVAL_MIN}min lookback={LOOKBACK_MIN}min cleanup={CLEANUP_INTERVAL_MIN}min")
    log("INFO", f"Service started — interval={INTERVAL_MIN}min lookback={LOOKBACK_MIN}min cleanup={CLEANUP_INTERVAL_MIN}min")

    run_hardlink()
    run_cleanup()
    last_cleanup = time.time()
    # → last_cleanup = 1748526727.4  (timestamp of when cleanup ran)

    while True:
        time.sleep(INTERVAL_MIN * 60)
        # sleeps 300 seconds (5 minutes)

        try:
            run_hardlink()
        except Exception as e:
            log("ERROR", f"Unhandled exception in hardlink: {e}")
            print(f"[ERROR] hardlink: {e}")

        if time.time() - last_cleanup >= CLEANUP_INTERVAL_MIN * 60:
            # time.time()              = 1748526727.4  (now)
            # last_cleanup             = 1748526127.4  (when cleanup last ran)
            # time.time() - last_cleanup = 600.0       (seconds elapsed)
            # CLEANUP_INTERVAL_MIN * 60  = 600         (10 minutes in seconds)
            # 600.0 >= 600 → True → run cleanup
            try:
                run_cleanup()
            except Exception as e:
                log("ERROR", f"Unhandled exception in cleanup: {e}")
                print(f"[ERROR] cleanup: {e}")
            last_cleanup = time.time()
