#!/usr/bin/env python3

import argparse
# import datetime
import json, codecs
import locale
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
from functools import wraps

import cherrypy
import psutil
from unidecode import unidecode
from flask import *
from flask.logging import logging
from flask_paginate import Pagination, get_page_parameter

import karaoke
from constants import VERSION
from collections import defaultdict
from lib.get_platform import *
from lib.vlcclient import get_default_vlc_path

try:
	from urllib.parse import quote, unquote
except ImportError:
	from urllib import quote, unquote

from tkinter import Tk
from tkinter.filedialog import askdirectory
import datetime
from datetime import datetime, timedelta
import sqlite3


def get_db_connection():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS songbook_table (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_name TEXT,
        artist TEXT,
        title TEXT,
		company TEXT,
		date_time TEXT,
	    song_path TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS history_table (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
		song_id INTEGER,
        date_time TEXT,
		selectedby TEXT,
		FOREIGN KEY (song_id) REFERENCES songbook_table (id)
    	)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS favorite_table (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
		song_id INTEGER,
        date_time TEXT,
		selectedby TEXT,
		FOREIGN KEY (song_id) REFERENCES songbook_table (id)
    	)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS srt_table (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        srt_path TEXT
    	)''')
    
    conn.commit()
    conn.close()

init_database()

settings = codecs.open("res/settings.json","r","utf-8")
Settings = json.load(settings)


if Settings["loglevel"] != "NOTSET":
	logging.basicConfig(filename='tmp/myapp.log', level=Settings["loglevel"], 
						format='%(asctime)s %(levelname)s %(name)s %(filename)s %(lineno)d %(message)s')
	logger=logging.getLogger(__name__)

def save_settings():
    f = codecs.open('res/settings.json','w','utf-8')
    json.dump(Settings, f, sort_keys=True, indent=4, ensure_ascii=False)


app = Flask(__name__)
app.secret_key = os.urandom(24)
site_name = "PiKaraoke"
admin_password = Settings["admin_password"]
os.texts = defaultdict(lambda: "")
getString = lambda ii: os.texts[ii]
getString1 = lambda lang, ii: os.langs[lang].get(ii, os.langs['en_US'][ii])


# Define global symbols for Jinja templates 
@app.context_processor
def inject_stage_and_region():
	return {'getString': getString, 'getString1': getString}


@app.before_request
def preprocessor():
	client_lang = request.cookies.get('lang', None)
	if client_lang is None:
		lang_str = request.cookies.get('Accept-Language', os.lang)
		for k in [j for i in lang_str.split(';') for j in i.split(',')]:
			client_lang = find_language(k)
			if client_lang is not None:
				break
	request.client_lang = find_language(client_lang or os.lang)


def filename_from_path(file_path, remove_youtube_id = True):
	rc = os.path.basename(file_path)
	rc = os.path.splitext(rc)[0]
	if remove_youtube_id:
		try:
			rc = rc.split("---")[0]  # removes youtube id if present
		except TypeError:
			# more fun python 3 hacks
			rc = rc.split("---".encode("utf-8"))[0]
	return rc

def url_escape(filename):
	return quote(filename.encode("utf8"))

def is_admin():
	if (admin_password == None):
		return True
	if ('admin' in request.cookies):
		a = request.cookies.get("admin")
		if (a == admin_password):
			return True
	return False

@app.route("/")
def home():
	s = K.get_state()
	return render_template(
		"home.html",
		getString1 = lambda ii: getString1(request.client_lang, ii),
		site_title = site_name,
		title = "Home",
		show_transpose = K.use_vlc,
		transpose_value = K.now_playing_transpose,
		volume = s['volume'],
		admin = is_admin(),
		seektrack_value = s['time'],
		seektrack_max = s['length'],
		audio_delay = s['audiodelay'],
		vocal_info = K.get_vocal_info(),
	)

@app.route("/nowplaying")
def nowplaying():
	try:
		if K.switchingSong:
			return ""
		next_song = K.queue[0]["title"] if K.queue else None
		next_user = K.queue[0]["user"] if K.queue else None
		s = K.get_state()
		rc = {
			"now_playing": K.now_playing,
			"now_playing_user": K.now_playing_user,
			"up_next": next_song,
			"next_user": next_user,
			"is_paused": s['state'] == 'paused',
			"volume": s['volume'],
			"transpose_value": K.now_playing_transpose,
			"seektrack_value": s['time'],
			"seektrack_max": s['length'],
			"audio_delay": s['audiodelay'],
			"vol_norm": K.normalize_vol,
			"vocal_info": K.get_vocal_info()
		}
		if K.has_subtitle:
			rc['subtitle_delay'] = s['subtitledelay']
		return json.dumps(rc)
	except Exception as e:
		logging.error(f"Problem loading /nowplaying, pikaraoke may still be starting up: {e}\n{traceback.print_exc()}")
		return ""


@app.route("/get_lang_list")
def get_lang_list():
	return json.dumps({k: v[1] for k, v in os.langs.items()}, sort_keys = False)

@app.route("/change_language/<language>")
def change_language(language):
	try:
		set_language(language)
	except:
		logging.error(f"Failed to set server language to {language}")
	return os.lang

@app.route("/auth", methods = ["POST"])
def auth():
	d = request.form.to_dict()
	p = d["admin-password"]
	if (p == admin_password):
		resp = make_response(redirect('/'))
		expire_date = datetime.now()
		expire_date = expire_date + timedelta(days = 90)
		resp.set_cookie('admin', admin_password, expires = expire_date)
		flash(getString(1), "is-success")
	else:
		resp = make_response(redirect(url_for('login')))
		flash(getString(2), "is-danger")
	return resp

@app.route("/login")
def login():
	return render_template("login.html")

@app.route("/logout")
def logout():
	resp = make_response(redirect('/'))
	resp.set_cookie('admin', '')
	flash(getString(3), "is-success")
	return resp

@app.route("/get_vocal_todo_list/<vocal_device>")
def get_vocal_todo_list(vocal_device):
	K.vocal_device = vocal_device
	last_completed = request.headers['last_completed']
	if last_completed in K.rename_history:
		K.rename(last_completed, os.path.splitext(K.rename_history[last_completed])[0])
		K.rename_history.pop(last_completed)
	q = ([K.now_playing_filename] if K.now_playing_filename else []) + [i['file'] for i in K.queue]
	return json.dumps({'download_path': K.download_path, 'queue': q, 'use_DNN': K.use_DNN_vocal})

@app.route("/set_vocal_mode/<mode>")
def set_vocal_mode(mode):
	K.use_DNN_vocal = (mode.lower() == 'true')
	K.play_vocal()
	return ''

@app.route("/norm_vol/<mode>", methods = ["GET"])
def norm_vol(mode):
	K.enable_vol_norm(mode.lower() == 'true')
	return ''

@app.route("/queue")
def queue():
	return render_template(
		"queue.html", 
		getString1 = lambda ii: getString1(request.client_lang, ii), 
		queue = K.queue, 
		site_title = site_name, 
		title = "Queue", 
		admin = is_admin(),
		defaultsong = len(K.songbook_table),
		favoritesong = len(K.favorite_table),
		historysong = len(K.history_table),
		rdata = Settings["randomsongpath"])

@app.route("/get_queue/<last_hash>", methods = ["GET"])
def get_queue(last_hash):
	return json.dumps([K.queue, K.queue_hash]) if last_hash != K.queue_hash else ''

@app.route("/queue/addrandom", methods = ["GET"])
def add_random():
	amount = int(request.args["amount"])
	rc = K.queue_add_random(amount)
	if rc:
		flash(getString(4) % amount, "is-success")
	else:
		flash(getString(5), "is-warning")
	return redirect(url_for("queue"))

@app.route("/queue/edit", methods = ["GET"])
def queue_edit():
	action = request.args["action"]
	if action == "clear":
		K.queue_clear()
		flash(getString(6), "is-warning")
		return redirect(url_for("queue"))
	elif action == "move":
		try:
			id_from = request.args['from']
			id_to = request.args['to']
			id_size = request.args['size']
		except:
			flash(getString(7))

		result = K.queue_edit(None, "move", src=id_from, tgt=id_to, size=id_size)
		if result:
			flash(f"{getString(8)} {id_from}->{id_to}/{id_size}")
		else:
			flash(f"{getString(9)} {id_from}->{id_to}/{id_size}")
	else:
		song = request.args["song"]
		song = unquote(song)
		if action == "down":
			result = K.queue_edit(song, "down")
			if result:
				flash(getString(10) + song, "is-success")
			else:
				flash(getString(11) + song, "is-danger")
		elif action == "up":
			result = K.queue_edit(song, "up")
			if result:
				flash(getString(12) + song, "is-success")
			else:
				flash(getString(13) + song, "is-danger")
		elif action == "delete":
			result = K.queue_edit(song, "delete")
			if result:
				flash(getString(14) + song, "is-success")
			else:
				flash(getString(15) + song, "is-danger")
	return redirect(url_for("queue"))

import os

@app.route("/enqueue", methods=["POST", "GET"])
def enqueue():
	if "song[6]" in request.args:
		song = request.args["song[6]"]
	else:
		d = request.form.to_dict()
		song = d["song-to-add"]

	if "user" in request.args:
		user = request.args["user"]
	else:
		d = request.form.to_dict()
		user = d["song-added-by"]

	if os.path.exists(song):
		rc = K.enqueue(song, user)
		song_title = filename_from_path(song)
		return json.dumps({"song": song_title, "success": rc})
	else:
		conn = get_db_connection()
		c = conn.cursor()
		c.execute("SELECT id FROM songbook_table WHERE song_path = ?", (song,))
		row = c.fetchone()
		if row is not None:
			c.execute("DELETE FROM history_table WHERE song_id = ?", (row[0],))
			c.execute("DELETE FROM favorite_table WHERE song_id = ?", (row[0],))
			c.execute("DELETE FROM songbook_table WHERE id = ?", (row[0],))

			c.execute("SELECT * FROM songbook_table ORDER BY file_name")
			songbook_table = c.fetchall()
			K.songbook_table = songbook_table

			#Favorite Song Book
			c.execute('''
				SELECT songbook_table.*, favorite_table.*
				FROM favorite_table
				INNER JOIN songbook_table ON favorite_table.song_id = songbook_table.id
			''')
			favorite_table = c.fetchall()
			K.favorite_table = favorite_table

			#History Song Book
			c.execute('''
				SELECT songbook_table.*, history_table.*
				FROM history_table
				INNER JOIN songbook_table ON history_table.song_id = songbook_table.id
				ORDER BY history_table.date_time DESC
			''')
			history_table = c.fetchall()
			K.history_table = history_table

		conn.commit()
		conn.close()
		return json.dumps({"song": song, "danger": song})  # File not found


@app.route("/favorite", methods = ["POST", "GET"])
def favorite():
	song = request.args["song[6]"] #path
	song_title = filename_from_path(song) #filename
	user = request.args["user"]

	conn = get_db_connection()
	c = conn.cursor()
	c.execute('SELECT id FROM songbook_table WHERE song_path = ?', (song,))
	song_id = c.fetchone()
	date_time = datetime.now()

	c.execute('''INSERT INTO favorite_table (song_id, date_time, selectedby)
				VALUES (?, ?, ?)''',
			(song_id[0], date_time, user))
	c.execute('''
		SELECT songbook_table.*, favorite_table.*
		FROM favorite_table
		INNER JOIN songbook_table ON favorite_table.song_id = songbook_table.id
	''')
	K.favorite_table = c.fetchall()
	conn.commit()
	conn.close()
	return json.dumps({"song": song_title, "success": song})

@app.route("/skip")
def skip():
	K.skip()
	return ''

@app.route("/pause")
def pause():
	K.pause()
	return json.dumps(K.is_paused)

@app.route("/transpose/<semitones>", methods = ["GET"])
def transpose(semitones):
	K.play_transposed(semitones)
	return ''

@app.route("/play_vocal/<mode>", methods = ["GET"])
def play_vocal(mode):
	K.play_vocal(mode)
	return ''

@app.route("/seek/<goto_sec>", methods = ["GET"])
def seek(goto_sec):
	K.seek(goto_sec)
	return ''

@app.route("/audio_delay/<delay_val>", methods = ["GET"])
def audio_delay(delay_val):
	res = K.set_audio_delay(delay_val)
	return json.dumps(res)

@app.route("/subtitle_delay/<delay_val>", methods = ["GET"])
def subtitle_delay(delay_val):
	res = K.set_subtitle_delay(delay_val)
	return json.dumps(res)

@app.route("/restart")
def restart():
	K.restart()
	return redirect(url_for("home"))

@app.route("/vol_up")
def vol_up():
	return str(K.vol_up())

@app.route("/vol_down")
def vol_down():
	return str(K.vol_down())

@app.route("/vol/<volume>")
def vol_set(volume):
	return str(K.vol_set(volume))

@app.route("/search", methods = ["GET"])
def search():
	if "search_string" in request.args:
		search_string = request.args["search_string"]
		search_nonkaraoke = request.args.get('non_karaoke', 'false') == "true"
		if search_nonkaraoke:
			search_results = K.get_search_results(search_string)
		else:
			search_results = K.get_karaoke_search_results(search_string)
	else:
		search_string = None
		search_results = None
		search_nonkaraoke = False
	return render_template(
		"search.html",
		getString1 = lambda ii: getString1(request.client_lang, ii),
		site_title = site_name,
		title = "Search",
		songs = K.songbook_table,
		search_results = search_results,
		search_string = search_string,
		search_nonkaraoke = search_nonkaraoke
	)

@app.route("/autocomplete")
def autocomplete():
	q = request.args.get('q').lower()
	result = []
	for each in K.songbook_table:
		if q in each[6].lower():
			result.append({"path": each[6], "fileName": K.filename_from_path(each[6]), "type": "autocomplete"})
	response = app.response_class(
		response = json.dumps(result),
		mimetype = 'application/json'
	)
	return response

@app.route("/downlod_quality" , methods=['GET', 'POST'])
def downlod_quality():
	select = request.form.get('comp_select')
	Settings["quality"] = str(select)
	save_settings()
	return redirect(url_for("info"))

@app.route("/randomsongfrom" , methods=['GET', 'POST'])
def randomsongfrom():
	select1 = request.form.get('randomsongfrom_select_que')
	Settings["randomsongpath"] = str(select1)
	save_settings()
	return redirect(url_for("queue"))

@app.route("/browse", methods = ["GET", 'POST'])
def browse():
	search = bool(request.args.get('q'))
	page = request.args.get(get_page_parameter(), type = int, default = 1)
	letter = request.args.get('letter')

	if Settings["song_list"] == "Default":
		song_book = K.songbook_table

	if Settings["song_list"] == "Favorite":
		data = K.favorite_table
		latest_rows = defaultdict(lambda: None)
		# Create a counter dictionary to count occurrences of values in the second column
		counter = defaultdict(int)
		# Iterate over the data and keep only the latest row for each value in the second column
		for row in data:
			key = row[8]
			counter[key] += 1
			if latest_rows[key] is None or row[9] > latest_rows[key][9]:
				latest_rows[key] = row
		# Retrieve the updated data with the latest rows
		data_with_latest = list(latest_rows.values())

		data_with_counter = [(row[0],row[1],row[2],row[3],row[4],row[5],row[6],row[7], row[8],\
		 row[9], row[10], counter[row[8]]) for row in data_with_latest]
		song_book = sorted(data_with_counter, key=lambda x: x[11], reverse=True)

	if Settings["song_list"] == "History":
		song_book = K.history_table
		# song_book.reverse()

	select = request.form.get('filtersong')
	if select != None:
		available_songs = []
		for ls in song_book:
			if select.casefold() in ls[6].casefold():
				available_songs.append(ls)
	else:
		available_songs = song_book

	if letter:
		available_songs = []

		if letter == "numeric":
			for file_name in song_book:
				if not file_name[1].islower():
					available_songs.append(file_name)
		else:
			for file_name in song_book:
				if file_name[1].startswith(letter):
					available_songs.append(file_name)
	getString2 = lambda ii: getString1(request.client_lang, ii)

	if "sort" in request.args and request.args["sort"] == "date":
		# songs = sorted(available_songs, key = lambda x: os.path.getctime(x))
		songs = song_book
		songs.reverse()
		sort_order = "Date"
		sort_order_text = getString2(99)
	else:
		songs = available_songs
		sort_order = "Alphabetical"
		sort_order_text = getString2(100)

	results_per_page = 500
	pagination = Pagination(css_framework = 'bulma', page = page, total = len(songs), search = search, search_msg = getString2(103),
	                        record_name = getString2(101), display_msg = getString2(102), per_page = results_per_page)
	start_index = (page - 1) * (results_per_page - 1)

	return render_template(
		"files.html",
		getString1 = getString2,
		pagination = pagination,
		sort_order = sort_order,
		sort_order_text = sort_order_text,
		site_title = site_name,
		letter = letter,
		title = getString2(98),
		songs = songs[start_index:start_index + results_per_page],
		admin = is_admin(),
		song_list_data = Settings["song_list"]
		# song_list_data = [{'name': Settings["song_list"]}, {'name': 'Favorite'}, {'name': 'History'}]
	)
@app.route("/song_book" , methods=['GET', 'POST'])
def song_book():
	browse_list = request.form.get('browse_list')
	Settings["song_list"] = browse_list
	save_settings()
	return redirect(url_for("browse"))

def transform_boolean(dct, S):
	return {k: ((v=='on') if k in S else v) for k, v in dct.items()}

@app.route("/download", methods = ["POST"])
def download():
	d = transform_boolean(request.form.to_dict(), {'enqueue', 'include_subtitles'})
	enqueue = d.get('enqueue', False)

	# download in the background since this can take a few minutes
	t = threading.Thread(target = K.download_video, kwargs = d)
	t.daemon = True
	t.start()

	return getString(16) + d["song_url"] + '\n' + getString(17 if enqueue else 18)

@app.route("/check_download", methods = ["POST"])
def check_download():
	ret = K.downloading_songs.get(request.values.get('url', None), 1)
	return str(ret)

@app.route("/qrcode")
def qrcode():
	return send_file(K.qr_code_path, mimetype = "image/png")

@app.route("/logo")
def logo():
	return send_file(K.logo_path, mimetype="image/png")

@app.route("/files/delete", methods = ["GET"])
def delete_file():
	if "song" in request.args:
		song_path = request.args["song"]
		if K.is_song_in_queue(song_path):
			flash(getString(19) + song_path, "is-danger")
		else:
			K.delete(song_path)
			flash(getString(20) + song_path, "is-warning")
	else:
		flash(getString(21), "is-danger")
	return redirect(url_for("browse"))

@app.route("/files/edit", methods = ["GET", "POST"])
def edit_file():
	queue_error_msg = getString(22)
	if "song[6]" in request.args:
		song_path = request.args["song[6]"]
		if song_path == K.now_playing_filename:
			flash(queue_error_msg + song_path, "is-danger")
			return redirect(url_for("browse"))
		else:
			return render_template("edit.html", getString1 = lambda ii: getString1(request.client_lang, ii), site_title = site_name, title = getString(23), song = song_path.encode("utf-8"))
	else:
		d = request.form.to_dict()
		if "new_file_name" in d and "old_file_name" in d:
			new_name = d["new_file_name"]
			old_name = d["old_file_name"]
			if old_name == K.now_playing_filename:
				flash(queue_error_msg + old_name, "is-danger")
			else:
				# check if new_name already exist
				file_extension = os.path.splitext(old_name)[1]
				if os.path.isfile(os.path.join(K.download_path, new_name + file_extension)):
					flash(getString(24) % (old_name, new_name + file_extension), "is-danger")
				else:
					K.rename(old_name, new_name)
					flash(getString(25) % (old_name, new_name), "is-warning")
		else:
			flash(getString(26), "is-danger")
		return redirect(url_for("browse"))

@app.route("/splash")
def splash():
	return render_template(
		"splash.html",
		getString1 = lambda ii: getString1(request.client_lang, ii),
		blank_page=True,
		url="http://" + request.host
	)

@app.route("/info")
def info():
	url = K.url
	# cpu
	cpu = str(psutil.cpu_percent()) + "%"
	# mem
	memory = psutil.virtual_memory()
	available = round(memory.available / 1024.0 / 1024.0, 1)
	total = round(memory.total / 1024.0 / 1024.0, 1)
	memory = str(available) + "MB free / " + str(total) + "MB total ( " + str(memory.percent) + "% )"
	# disk
	disk = psutil.disk_usage("/")
	# Divide from Bytes -> KB -> MB -> GB
	free = round(disk.free / 1024.0 / 1024.0 / 1024.0, 1)
	total = round(disk.total / 1024.0 / 1024.0 / 1024.0, 1)
	disk = str(free) + "GB free / " + str(total) + "GB total ( " + str(disk.percent) + "% )"

	# whether screencapture.sh and vocal_splitter.py is running
	getString2 = lambda ii: getString1(request.client_lang, ii)
	get_status = lambda t: getString2(27) if t is None else (getString2(28) if t else getString2(29))
	screencapture = K.streamer_alive()
	vocalsplitter = K.vocal_alive()
	vocal_extra = ''
	if vocalsplitter:
		vocal_extra = getString2(30) if K.vocal_device == 'cpu' else getString2(31)

	# youtube-dl
	youtubedl_version = K.youtubedl_version

	is_pi = get_platform() == "raspberry_pi"
	return render_template(
		"info.html",
		getString1 = getString2,
		langs = os.langs, lang = os.lang,
		site_title = site_name,
		ostype = sys.platform.upper(),
		title = "Info",
		url = url,
		memory = memory,
		cpu = cpu,
		disk = disk,
		youtubedl_version = youtubedl_version,
		is_pi = is_pi,
		use_DNN = K.use_DNN_vocal,
		norm_vol = K.normalize_vol,
		pikaraoke_version = VERSION,
		download_path = Settings["Song_dir"],
		# download_path = K.args.download_path,
		num_of_songs = len(K.songbook_table),
		screencapture = get_status(screencapture),
		vocalsplitter = get_status(vocalsplitter) + vocal_extra,
		platform = K.platform,
		admin = is_admin(),
		admin_enabled = admin_password != None,
		data=[{'name': Settings["quality"]}, {'name':'360p'}, {'name':'480p'}, {'name':'720p'}, {'name':'1080p'}]
		# rdata = [{'name': Settings["randomsongpath"]}, {'name': 'Default'}, {'name': 'History'},{'name': 'Favorite'}]
	)

# Delay system commands to allow redirect to render first
def delayed_halt(cmd):
	time.sleep(3)
	if K.vocal_process is not None and K.vocal_process.is_alive():
		K.vocal_process.terminate()
	K.queue_clear()  # stop all pending omxplayer processes
	cherrypy.engine.stop()
	cherrypy.engine.exit()
	K.stop()
	if cmd == 0:
		os.system('(sleep 2 && tmux kill-session -t PiKaraoke) &')
		sys.exit()
	if cmd == 1:
		os.system("shutdown now")
	if cmd == 2:
		os.system("reboot")
	if cmd == 3:
		process = subprocess.Popen(["raspi-config", "--expand-rootfs"])
		process.wait()
		os.system("reboot")


def update_youtube_dl():
	K.upgrade_youtubedl()

@app.route("/update_ytdl")
def update_ytdl():
	if (is_admin()):
		flash(getString(32), "is-warning")
		th = threading.Thread(target = update_youtube_dl)
		th.start()
	else:
		flash(getString(33), "is-danger")
	return redirect(url_for("home"))

@app.route("/bg-process/<cmd>")
def bg_process(cmd):
	if cmd == 'streamer-restart':
		K.streamer_restart()
	elif cmd == 'streamer-stop':
		K.streamer_stop()
	elif cmd == 'vocal-restart':
		K.vocal_restart()
	elif cmd == 'vocal-stop':
		K.vocal_stop()
	return ''

@app.route("/quit")
def quit():
	if (is_admin()):
		flash(getString(35), "is-warning")
		th = threading.Thread(target = delayed_halt, args = [0])
		th.start()
	else:
		flash(getString(36), "is-danger")
	return redirect(url_for("home"))

@app.route("/shutdown")
def shutdown():
	if (is_admin()):
		flash(getString(37), "is-danger")
		th = threading.Thread(target = delayed_halt, args = [1])
		th.start()
	else:
		flash(getString(38), "is-danger")
	return redirect(url_for("home"))

@app.route("/reboot")
def reboot():
	if (is_admin()):
		flash(getString(39), "is-danger")
		th = threading.Thread(target = delayed_halt, args = [2])
		th.start()
	else:
		flash(getString(40), "is-danger")
	return redirect(url_for("home"))

@app.route("/expand_fs")
def expand_fs():
	if (is_admin() and platform == "raspberry_pi"):
		flash(getString(41), "is-danger")
		th = threading.Thread(target = delayed_halt, args = [3])
		th.start()
	elif (platform != "raspberry_pi"):
		flash(getString(42), "is-danger")
	else:
		flash(getString(43), "is-danger")
	return redirect(url_for("home"))

# Handle sigterm, apparently cherrypy won't shut down without explicit handling
signal.signal(signal.SIGTERM, lambda signum, stack_frame: K.stop())

def get_default_youtube_dl_path(platform):
	# use Python's cross-platform way
	shutil_path = shutil.which('yt-dlp')
	if shutil_path:
		return shutil_path

	if platform == "windows":
		choco_ytdl_path = r"C:\ProgramData\chocolatey\bin\yt-dlp.exe"
		scoop_ytdl_path = os.path.expanduser(r"~\scoop\shims\yt-dlp.exe")
		if os.path.isfile(choco_ytdl_path):
			return choco_ytdl_path
		if os.path.isfile(scoop_ytdl_path):
			return scoop_ytdl_path
		return Settings["ytpath"]
	default_ytdl_unix_path = "/usr/local/bin/yt-dlp"
	if platform == "osx":
		if os.path.isfile(default_ytdl_unix_path):
			return default_ytdl_unix_path
		else:
			# just a guess based on the default python 3 install in OSX monterey
			return "/Library/Frameworks/Python.framework/Versions/3.10/bin/yt-dlp"
	else:
		return default_ytdl_unix_path

def get_default_dl_dir(platform):
	if platform == "raspberry_pi":
		return "/usr/lib/pikaraoke/songs"
	else:
		legacy_directory = os.path.expanduser(Settings["Song_dir"])
		if os.path.exists(legacy_directory):
			print("LEGACY DIRECTORY: "+ legacy_directory)
			return legacy_directory
		else:
			print("LEGACY DIRECTORY: "+ legacy_directory)
			return os.path.expanduser(Settings["Song_dir"])

@app.route("/refresh")
def refresh():
	if (is_admin()):
		K.get_available_songs()
	else:
		flash(getString(34), "is-danger")
	return redirect(url_for("browse"))
@app.route("/set_songpath")
def set_songpath():
	if (is_admin()):
		root = Tk() 
		root.wm_attributes('-topmost', 1)
		root.withdraw()
		filepath=askdirectory(parent = root, initialdir='shell:MyComputerFolder', title="Dialog box")
		if filepath != "":
			if not filepath.endswith("/"):
				filepath += "/"
				Settings["Song_dir"] = filepath
				# K.set_download_path()
				get_default_dl_dir(platform)
				print("Settings song path change: "+Settings["Song_dir"])
				save_settings()
		else:
			pass
		return redirect(url_for("info"))
				

if __name__ == "__main__":

	from tkinter import filedialog, messagebox

	platform = get_platform()
	default_port = Settings["browser_port"]
	default_volume = 0
	default_splash_delay = 3
	default_log_level = logging.INFO

	default_dl_dir = get_default_dl_dir(platform)
	default_omxplayer_path = "/usr/bin/omxplayer"
	default_adev = "both"
	default_youtubedl_path = get_default_youtube_dl_path(platform)
	default_vlc_path = get_default_vlc_path(platform)
	default_vlc_port = Settings["vlc_port"]

	if Settings["Song_dir"] == "" or os.path.exists(Settings["Song_dir"]) == False:
		root = Tk() 
		root.wm_attributes('-topmost', 1)
		root.withdraw()
		messagebox.showwarning("Directory Not Found", "Please select your prepared directory for your karaoke files.")
		filepath=askdirectory(parent = root, initialdir='shell:MyComputerFolder', title="Select song directory")
		if filepath != "":
			if not filepath.endswith("/"):
				filepath += "/"
				Settings["Song_dir"] = filepath
				get_default_dl_dir(platform)
				print("Settings song path change: "+Settings["Song_dir"])
				save_settings()
		else:
			pass
	# parse CLI args
	parser = argparse.ArgumentParser()

	parser.add_argument(
		"-u", "--nonroot-user",
		help = "Since tmux must be launched by a non-root user (to run pacmd to select recording source), this is required for sending keys to tmux.",
		default = None,
	)
	parser.add_argument(
		"-p", "--port",
		help = f"Desired http port (default: {default_port})",
		default = default_port,
	)
	parser.add_argument(
		"-d", "--download-path",
		help = f"Desired path for downloaded songs. (default: {default_dl_dir})",
		default = default_dl_dir,
	)
	parser.add_argument(
		"-o", "--omxplayer-path",
		help = f"Path of omxplayer. Only important to raspberry pi hardware. (default: {default_omxplayer_path})",
		default = default_omxplayer_path,
	)
	parser.add_argument(
		"-y", "--youtubedl-path",
		help = f"Path of youtube-dl. (default: {default_youtubedl_path})",
		default = default_youtubedl_path,
	)
	parser.add_argument(
		"-v", "--volume",
		help = f"If using omxplayer, the initial player volume is specified in millibels. Negative values ok. (default: {default_volume} , Note: 100 millibels = 1 decibel).",
		default = default_volume,
	)
	parser.add_argument(
		"-V", "--run-vocal",
		help = "Explicitly run vocal-splitter process from the main program (by default, it only run explicitly in Windows)",
		action = 'store_true',
	)
	parser.add_argument(
		"-nv", "--normalize-vol",
		help = "Enable volume normalization",
		action = 'store_true',
	)
	parser.add_argument(
		"-s", "--splash-delay",
		help = f"Delay during splash screen between songs (in secs). (default: {default_splash_delay} )",
		default = default_splash_delay,
	)
	parser.add_argument(
		"-L", "--lang",
		help = f"Set display language (default: None, set according to the current system locale {locale.getdefaultlocale()[0]})",
		default = locale.getdefaultlocale()[0],
	)
	parser.add_argument(
		"-l", "--log-level",
		help = f"Logging level int value (DEBUG: 10, INFO: 20, WARNING: 30, ERROR: 40, CRITICAL: 50). (default: {default_log_level} )",
		default = default_log_level,
	)
	parser.add_argument(
		"--hide-ip",
		action = "store_true",
		help = "Hide IP address from the screen.",
	)
	parser.add_argument(
		"--hide-raspiwifi-instructions",
		action = "store_true",
		help = "Hide RaspiWiFi setup instructions from the splash screen.",
	)
	parser.add_argument(
		"--hide-splash-screen",
		action = "store_true",
		help = "Hide splash screen before/between songs.",
	)
	parser.add_argument(
		"--adev",
		help = f"Pass the audio output device argument to omxplayer. Possible values: hdmi/local/both/alsa[:device]."
		       f" If you are using a rpi USB soundcard or Hifi audio hat, try: 'alsa:hw:0,0' Default: '{default_adev}'",
		default = default_adev,
	)
	parser.add_argument(
		"--dual-screen",
		action = "store_true",
		help = "Output video to both HDMI ports (raspberry pi 4 only)",
	)
	parser.add_argument(
		"--high-quality",
		action = "store_true",
		help = "Download higher quality video. Note: requires ffmpeg and may cause CPU, download speed, and other performance issues",
	)
	parser.add_argument(
		"--use-omxplayer",
		action = "store_true",
		help = "Use OMX Player to play video instead of the default VLC Player. This may be better-performing on older raspberry pi devices."
		       " Certain features like key change and cdg support wont be available. Note: if you want to play audio to the headphone jack on a rpi,"
		       " you'll need to configure this in raspi-config: 'Advanced Options > Audio > Force 3.5mm (headphone)'",
	)
	parser.add_argument(
		"--use-vlc",
		action = "store_true",
		help = "Use VLC Player to play video. Enabled by default. Note: if you want to play audio to the headphone jack on a rpi, see troubleshooting steps in README.md",
	)
	parser.add_argument(
		"--vlc-path",
		help = f"Full path to VLC (Default: {default_vlc_path})",
		default = default_vlc_path,
	)
	parser.add_argument(
		"--vlc-port",
		help = f"HTTP port for VLC remote control api (Default: {default_vlc_port})",
		default = default_vlc_port,
	)
	parser.add_argument(
		"--logo-path",
		help = "Path to a custom logo image file for the splash screen. Recommended dimensions ~ 500x500px",
		default = None,
	)
	parser.add_argument(
		"--show-overlay",
		action = "store_true",
		help = "Show overlay on top of video with pikaraoke QR code and IP",
	)
	parser.add_argument(
		'-w', "--windowed",
		action = "store_true",
		help = "Start PiKaraoke in windowed mode",
	)
	parser.add_argument(
		"--admin-password",
		help = "Administrator password, for locking down certain features of the web UI such as queue editing, player controls, song editing, and system shutdown. If unspecified, everyone is an admin.",
		default = None,
	)
	parser.add_argument(
		"--developer-mode",
		help = "Run in flask developer mode. Only useful for tweaking the web UI in real time. Will disable the splash screen due to pygame main thread conflicts and may require FLASK_ENV=development env variable for full dev mode features.",
		action = "store_true",
	)
	args = parser.parse_args()

	set_language(args.lang)

	if (args.admin_password):
		admin_password = args.admin_password

	app.jinja_env.globals.update(filename_from_path = filename_from_path)
	app.jinja_env.globals.update(url_escape = quote)

	# Handle OMX player if specified
	if platform == "raspberry_pi" and args.use_omxplayer:
		args.use_vlc = False
	else:
		args.use_vlc = True

	# check if required binaries exist
	if not os.path.isfile(args.youtubedl_path):
		# print(getString(44) + args.youtubedl_path)
		sys.exit(1)
	if args.use_vlc and not os.path.isfile(args.vlc_path):
		# print(getString(45) + args.vlc_path)
		sys.exit(1)
	if platform == "raspberry_pi" and not args.use_vlc and not os.path.isfile(args.omxplayer_path):
		# print(getString(46) + args.omxplayer_path)
		sys.exit(1)

	# setup/create download directory if necessary
	args.dl_path = os.path.expanduser(Settings["Song_dir"])
	if not args.dl_path.endswith("/"):
		args.dl_path += "/"
	if not os.path.exists(args.dl_path):
		print(getString(47) + args.dl_path)
		os.makedirs(args.dl_path)

	if args.developer_mode:
		logging.warning("Splash screen is disabled in developer mode due to main thread conflicts")
		args.hide_splash_screen = True

	# Configure karaoke process
	global K
	K = karaoke.Karaoke(args)

	if (args.developer_mode):
		th = threading.Thread(target = K.run)
		th.start()
		app.run(debug = True, port = args.port)
	else:
		# Start the CherryPy WSGI web server
		cherrypy.tree.graft(app, "/")
		# Set the configuration of the web server
		cherrypy.config.update(
			{
				"engine.autoreload.on": False,
				"log.screen": True,
				"server.socket_port": int(args.port),
				"server.socket_host": "0.0.0.0",
			}
		)
		cherrypy.engine.start()
		K.run()
		cherrypy.engine.exit()

	sys.exit()
