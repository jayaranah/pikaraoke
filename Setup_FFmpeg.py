import winreg
import os
import tkinter as tk
from tkinter import filedialog, messagebox

def show_notification(message, is_warning=False):
    root = tk.Tk()
    root.withdraw()
    if is_warning:
        messagebox.showwarning("Environment Variable Update - Warning", message)
    else:
        messagebox.showinfo("Environment Variable Update", message)

def add_directory_to_path():
    try:
        # Get the current working directory
        script_directory = os.getcwd()
        ffmpeg_directory = os.path.join(script_directory, "FFmpeg\\bin")

        if not os.path.exists(ffmpeg_directory):
            # Prompt user to select the FFmpeg\bin directory manually
            root = tk.Tk()
            root.withdraw()
            messagebox.showinfo("FFmpeg\\bin Directory", "Please select the FFmpeg\\bin directory.")
            ffmpeg_directory = filedialog.askdirectory(initialdir=script_directory, title="Select FFmpeg\\bin Directory")
            if not ffmpeg_directory:
                show_notification("No directory selected.", is_warning=True)
                return

        ffmpeg_directory = ffmpeg_directory.replace("/", "\\")

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Environment', 0, winreg.KEY_ALL_ACCESS) as reg_key:
            path_value, _ = winreg.QueryValueEx(reg_key, 'Path')
            paths = path_value.split(';') if path_value else []

            # Check if any path already contains "FFmpeg\bin"
            ffmpeg_paths = [path for path in paths if "FFmpeg\\bin" in path]
            if ffmpeg_paths:
                show_notification(f"FFmpeg paths {ffmpeg_paths} already exist in the user's environment variable.")
                return

            # Check if the directory is already in the path
            if ffmpeg_directory in paths:
                show_notification(f"FFmpeg path '{ffmpeg_directory}' is already in the user's environment variable.")
                return

            # Add the directory to the path
            paths.append(ffmpeg_directory)
            path_value = ';'.join(paths)
            winreg.SetValueEx(reg_key, 'Path', 0, winreg.REG_EXPAND_SZ, path_value)
            show_notification(f"FFmpeg path '{ffmpeg_directory}' added to the user's environment variable.")

            # Update the current process environment variable
            os.environ['Path'] = path_value
            print("Environment variable updated for the current process.")
    except Exception as e:
        show_notification(f"Error: {e}", is_warning=True)

# Usage example
add_directory_to_path()
