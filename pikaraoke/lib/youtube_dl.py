import logging
import subprocess
import sys
import platform


def get_youtubedl_version(youtubedl_path):
    try:
        return subprocess.check_output([youtubedl_path, "--version"]).strip().decode("utf8")
    except subprocess.CalledProcessError:
        return "unknown"


def get_youtube_id_from_url(url):
    if "v=" in url:  # accomodates youtube.com/watch?v= and m.youtube.com/?v=
        s = url.split("watch?v=")
    else:  # accomodates youtu.be/
        s = url.split("u.be/")
    if len(s) == 2:
        if "?" in s[1]:  # Strip uneeded Youtube Params
            s[1] = s[1][0 : s[1].index("?")]
        return s[1]
    else:
        logging.error("Error parsing youtube id from url: " + url)
        return None


def upgrade_youtubedl(youtubedl_path):
    try:
        output = (
            subprocess.check_output([youtubedl_path, "-U"], stderr=subprocess.STDOUT)
            .decode("utf8")
            .strip()
        )
    except subprocess.CalledProcessError as e:
        output = e.output.decode("utf8") if e.output else ""
    
    logging.info(output)
    
    if "You installed yt-dlp with pip or using the wheel from PyPi" in output:
        # Check if we're in a virtual environment
        in_venv = hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)
        
        # Base args - only add --break-system-packages if not in venv
        args = ["install", "--upgrade", "yt-dlp"]
        if not in_venv:
            args.append("--break-system-packages")
        
        # Determine pip commands to try based on platform
        if platform.system() == "Windows":
            pip_commands = ["pip", "pip3"]
        else:
            pip_commands = ["pip3", "pip"]
        
        success = False
        for pip_cmd in pip_commands:
            try:
                logging.info(f"Attempting youtube-dl upgrade via {pip_cmd}...")
                output = (
                    subprocess.check_output([pip_cmd] + args, stderr=subprocess.STDOUT)
                    .decode("utf8")
                    .strip()
                )
                logging.info(output)
                success = True
                break
            except FileNotFoundError:
                logging.warning(f"{pip_cmd} not found, trying next option...")
                continue
            except subprocess.CalledProcessError as e:
                error_output = e.output.decode("utf8") if e.output else str(e)
                logging.warning(f"{pip_cmd} upgrade failed: {error_output}")
                
                # If --break-system-packages failed, try without it
                if "--break-system-packages" in args:
                    try:
                        logging.info(f"Retrying {pip_cmd} without --break-system-packages...")
                        args_no_break = ["install", "--upgrade", "yt-dlp"]
                        output = (
                            subprocess.check_output([pip_cmd] + args_no_break, stderr=subprocess.STDOUT)
                            .decode("utf8")
                            .strip()
                        )
                        logging.info(output)
                        success = True
                        break
                    except subprocess.CalledProcessError as e2:
                        error_output2 = e2.output.decode("utf8") if e2.output else str(e2)
                        logging.warning(f"{pip_cmd} upgrade failed even without --break-system-packages: {error_output2}")
                        continue
        
        if not success:
            logging.error("All pip upgrade attempts failed. Continuing with current version.")
    
    # Always try to get the version, even if upgrade failed
    youtubedl_version = get_youtubedl_version(youtubedl_path)
    return youtubedl_version


def build_ytdl_download_command(
    youtubedl_path, video_url, download_path, high_quality=False, youtubedl_proxy=None
):
    dl_path = download_path + "%(title)s---%(id)s.%(ext)s"
    file_quality = (
        "bestvideo[ext!=webm][height<=1080]+bestaudio[ext!=webm]/best[ext!=webm]"
        if high_quality
        else "mp4"
    )
    cmd = [youtubedl_path, "-f", file_quality, "-o", dl_path]
    if youtubedl_proxy:
        cmd += ["--proxy", youtubedl_proxy]
    cmd += [video_url]
    return cmd
