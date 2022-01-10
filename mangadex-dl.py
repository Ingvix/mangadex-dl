#!/usr/bin/env python3

# Copyright (c) 2019-2021 eli fessler
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

import requests, time, os, sys, re, json, html, zipfile, argparse, shutil

A_VERSION = "0.6"
progress_indicator = ["|", "/", "–", "\\"]

def pad_filename(str):
	digits = re.compile('(\\d+)')
	pos = digits.search(str)
	if pos:
		return str[1:pos.start()] + pos.group(1).zfill(3) + str[pos.end():]
	else:
		return str

def float_conversion(tupl):
	try:
		x = float(tupl[0]) # (chap_num, chap_uuid)
	except ValueError: # empty string for oneshot
		x = 0
	return x

def find_id_in_url(url_parts):
	for part in url_parts:
		if "-" in part:
			return part

def zpad(num):
	if "." in num:
		parts = num.split('.')
		return "{}.{}".format(parts[0].zfill(3), parts[1])
	else:
		return num.zfill(3)

def get_uuid(manga_id):
	headers = {'Content-Type': 'application/json'}
	payload = '{"type": "manga", "ids": [' + str(manga_id) + ']}'
	try:
		r = requests.post("https://api.mangadex.org/legacy/mapping",
				headers=headers, data=payload)
	except:
		print("Error. Maybe the MangaDex API is down?")
		exit(1)
	try:
		resp = r.json()
		uuid = resp[0]["data"]["attributes"]["newId"]
	except:
		print("Please enter a valid MangaDex manga (not chapter) URL or ID.")
		exit(1)
	return uuid

def get_title(uuid, lang_code):
	r = requests.get("https://api.mangadex.org/manga/{}".format(uuid))
	resp = r.json()
	try:
		title = resp["data"]["attributes"]["title"][lang_code]
	except KeyError: # if no manga title in requested dl language
		try:
			# lookup in altTitles
			alt_titles = {}
			titles = resp["data"]["attributes"]["altTitles"]
			for val in titles:
				alt_titles.update(val)
			title = alt_titles[lang_code]
		except:
			# fallback to English title
			try:
				title = resp["data"]["attributes"]["title"]["en"]
			except:
				print("Error - could not retrieve manga title.")
				exit(1)
	return title

def uniquify(*args, start="", end=""):
	counter = 1
	dest_folder = os.path.join(*args, start + end)
	while os.path.exists(dest_folder):
		dest_folder = os.path.join(*args, "{}-{}{}".format(start, counter, end))
		counter += 1
	return dest_folder

def print_chaps(chapters):
	enum_chapters = enumerate(chapters, 1)
	s = ""
	amount = len(chapters)
	same_count = 0
	for i, chapter in enum_chapters:
		if  i < amount and chapter["attributes"]["chapter"]\
				== chapters[i]["attributes"]["chapter"]:
				same_count += 1
				continue
		else:
			if chapter["attributes"]["chapter"] is None:
				s += "Oneshot" 
			else:
				s += chapter["attributes"]["chapter"]
			if same_count:
				s += "({})".format(same_count+1)
				same_count = 0
			s += ", "
	print(s)

def print_vols(volumes, chapters):
	for key in volumes:
		chaps = [chapters[i] for i in volumes[key]]
		print("Vol. {} : ".format(key if key is not None else "N/A"),
				end='')
		print_chaps(chaps)

def get_names(type, path, key, chapter):
	uuids = [entry["id"]
			for entry in chapter["relationships"]
			if entry["type"] == type]
	names = []
	for id in uuids:
		r = requests.get("https://api.mangadex.org/{}/{}".format(path, id))
		name = r.json()["data"]["attributes"][key]
		names.append(name)
	return names

def print_bar(width, current=1, total=1, end="\n"):
	percent = current / total
	bar_fill = int(percent * width)
	bar = "{}{:>2}%[{:<{}}]".format(
			progress_indicator[(current)%4] * (current is not total),
			int(percent*100),
			"=" * bar_fill + ">" * (current is not total),
			width)
	print(bar, end=end, flush=True)

def dl(manga_id, lang_code, zip_up, ds, outdir, use_vols, same_chapter_mode,
		pref_lists):
	uuid = manga_id
	label = "volume" if use_vols else "chapter"

	if manga_id.isnumeric():
		uuid = get_uuid(manga_id)

	title = get_title(uuid, lang_code)
	print("\nTITLE: {}".format(html.unescape(title)))

	# check available chapters or volumes & get images
	chap_list = []
	if use_vols: vol_dict = {}
	content_ratings = "contentRating[]=safe"\
			"&contentRating[]=suggestive"\
			"&contentRating[]=erotica"\
			"&contentRating[]=pornographic"
	r = requests.get("https://api.mangadex.org/manga/{}/feed"\
			"?limit=0&translatedLanguage[]={}&{}"
			.format(uuid, lang_code, content_ratings))
	try:
		total = r.json()["total"]
	except KeyError:
		print("Error retrieving the chapters list. "\
				"Did you specify a valid language code?")
		exit(1)

	if total == 0:
		print("No chapters available to download!")
		exit(0)

	offset = 0
	while offset < total: # if more than 500 chapters!
		r = requests.get("https://api.mangadex.org/manga/{}/feed"\
				"?order[chapter]=asc&order[volume]=asc&limit=500"\
				"&translatedLanguage[]={}&offset={}&{}"
				.format(uuid, lang_code, offset, content_ratings))
		chaps = r.json()
		if use_vols:
			old_vol = ""
			index = 0
			for chapter in chaps["data"]:
				# don't include empty chapters (usually external)
				if chapter["attributes"]["pages"]:
					if chapter["attributes"]["volume"] != old_vol:
						old_vol = chapter["attributes"]["volume"]
						vol_dict[old_vol] = []
					vol_dict[old_vol].append(index)
					chap_list.append(chapter)
					index += 1
		else:
			chap_list += [c for c in chaps["data"] if c["attributes"]["pages"]]
		offset += 500

	# chap_list is not empty at this point
		print("Available " + label + "s:")
	if use_vols:
		print_vols(vol_dict, chap_list)
	else:
		print_chaps(chap_list)

	# i/o for chapters to download
	requested_chapters = []
	dl_list = input("\nEnter " + label + "(s) to download: ").strip()

	dl_list = [s.strip() for s in dl_list.split(',')]
	if use_vols:
		list_only_nums = [k for k in vol_dict]
		requested_volumes = []
	else:
		list_only_nums = [c["attributes"]["chapter"] for c in chap_list]
	for s in dl_list:
		if "-" in s: # range
			split = s.split('-')
			lower_bound = split[0]
			upper_bound = split[-1]
			try:
				lower_bound_i = list_only_nums.index(lower_bound)
			except ValueError:
				print("{} {} does not exist. Skipping range {}."
						.format(label.capitalize(), lower_bound, s))
				continue # go to next iteration of loop
			try:
				upper_bound_i = list_only_nums.index(upper_bound)
			except ValueError:
				print("{} {} does not exist. Skipping range {}."
						.format(label.capitalize(), upper_bound, s))
				continue
			if use_vols:
				s = list(vol_dict)[lower_bound_i:upper_bound_i+1]
				requested_volumes += s
				s = [chap_list[i] for k in s for i in vol_dict[k]]
			else:
				s = chap_list[lower_bound_i:upper_bound_i+1]
		elif s.lower() == "oneshot" and not use_vols:
			if None in list_only_nums:
				oneshot_idxs = [i
						for i, x in enumerate(list_only_nums)
						if x is None]
				s = []
				for idx in oneshot_idxs:
					s.append(chap_list[idx])
			else:
				print("{} {} does not exist. Skipping.".format(
					label.capitalize(), "Oneshot"))
				continue
		else:
			if use_vols:
				requested_volumes.append(s)
				s = [chap_list[i] for i in vol_dict[s]]
			else: # single number (but might be multiple chapters numbered this)
				chap_idxs = [i for i, x in enumerate(list_only_nums) if x == s]
				if len(chap_idxs) == 0:
					print("{} {} does not exist. Skipping.".format(
						label.capitalize(), s))
					continue
				s = []
				for idx in chap_idxs:
					s.append(chap_list[idx])

		requested_chapters += s

	# advanced handling of same numbered chapters
	checked_chapters = []
	same_chapters = []
	interrupt = False
	print("\nPreparing:")
	for i, chap in enumerate(requested_chapters):
		bar_width = min(100, shutil.get_terminal_size((0,0)).columns-6)
		if bar_width: print_bar(bar_width, i, len(requested_chapters), end="")
		# get names for groups and users if needed
		chap["groups"] = get_names("scanlation_group", "group", "name", chap)
		if "users" in prefs or not chap["groups"]:
			chap["users"] = get_names("user", "user", "username", chap)
		# gather the same numbered chapters
		if (len(s) > i+1 and 
			chap["attributes"]["chapter"]
			== s[i+1]["attributes"]["chapter"]):
			if not chap["users"]:
				chap["users"] = get_names("user", "user", "username", chap)
			same_chapters.append(chap)
		elif same_chapters:
			if not chap["users"]:
				chap["users"] = get_names("user", "user", "username", chap)
			same_chapters.append(chap)
			matched = False
			for key in prefs:
				names = [u
					for c in same_chapters
					for u in c[key]]
				for name in prefs[key]:
					if name in names:
						checked_chapters.append(
							same_chapters[names.index(name)])
						matched = True
						break
			if not matched: # handle according to the mode
				if same_chapter_mode == "all":
					checked_chapters += same_chapters
				elif same_chapter_mode == "last":
					checked_chapters.append(same_chapters[-1])
				elif same_chapter_mode == "first":
					checked_chapters.append(same_chapters[0])
				elif same_chapter_mode == "ask":
					interrupt = True
					print("Chapter {} has multiple entries:".format(
						same_chapters[0]["attributes"]["chapter"]))
					print("\n".join(map(
						lambda c: " {}) by {}{}".format(
							c[0]+1,
							", ".join(c[1]["users"]),
							" from "+", ".join(c[1]["groups"])),
						enumerate(same_chapters))))
					success = False
					while success is False:
						c_list = input("Enter which you wish to download: ")\
								.strip()
						c_list = [s.strip() for s in c_list.split(',')]
						for s in c_list:
							try:
								if "-" in s: # range
									split = s.split('-')
									lower_bound = int(split[0])
									upper_bound = int(split[-1])
									checked_chapters += same_chapters[
											lower_bound-1:upper_bound]
								else:
									checked_chapters.append(
											same_chapters[int(s)])
								success = True
							except ValueError:
								print("Undecipherable input. Try again.")
			del same_chapters[:]
		else:
			checked_chapters.append(chap)
		if not interrupt:
			interrupt = False
			print("\033[G", end="", flush=True)
	print_bar(bar_width)
	print("Done.")

	page_index = 0
	page_amount = sum(
			chapter["attributes"]["pages"] for chapter in checked_chapters)
	if use_vols:
		vol_amount = len(requested_volumes)
		vol_index = 0
	else:
		chap_amount = len(checked_chapters)
		chap_index = 0

	output = []
	output.append("Downloaded [{:{}}/{}] pages")
	output.append("of chapter {} [{:{}}/{}]")
	if use_vols:
		output.append("of volume {} [{:{}}/{}]")

	print("\nDownloading:")
	for index, chapter in enumerate(checked_chapters):
		# get chapter json(s)
		r = requests.get("https://api.mangadex.org/at-home/server/{}"
				.format(chapter["id"]))
		chapter_data = r.json()
		baseurl = chapter_data["baseUrl"]

		# make url list
		images = []
		accesstoken = ""
		chaphash = chapter_data["chapter"]["hash"]
		datamode = "dataSaver" if ds else "data"
		datamode2 = "data-saver" if ds else "data"
		errored = False

		for page_filename in chapter_data["chapter"][datamode]:
			images.append("{}/{}/{}/{}".format(
				baseurl, datamode2, chaphash, page_filename))

		# combine group names (or user names if no groups)
		groups = " & ".join(
				chapter["groups"] if chapter["groups"] else chapter["users"])
		groupname = " [{}]".format(re.sub('[/<>:"/\\|?*]', '-', groups))

		title = re.sub('[/<>:"/\\|?*]', '-', html.unescape(title))
		if (chapter["attributes"]["chapter"]) is None:
			chapnum = "Oneshot"
		else:
			chapnum = "c" + zpad(chapter["attributes"]["chapter"])

		if use_vols:
			current_vol = chapter["attributes"]["volume"]
			if chapter == chap_list[vol_dict[current_vol][0]]:
				chap_amount = sum(1 for chapter in checked_chapters
						if chapter["attributes"]["volume"] == current_vol)
				volnum = "v" + zpad(current_vol)
				vol_index += 1
				chap_index = 0
				if zip_up: # no need for unique names when zippin'
					dest_folder = os.path.join(outdir, title, "tmp")
					# remove any leftovers from failed runs
					if os.path.exists(dest_folder):
						shutil.rmtree(dest_folder)
				else:
					dest_folder = uniquify(
							os.getcwd(), outdir, title, start=volnum)
			chap_index += 1
		else:
			chap_index = index
			if zip_up:
				dest_folder = os.path.join(outdir, title, "tmp")
				if os.path.exists(dest_folder):
					shutil.rmtree(dest_folder)
			else:
				dest_folder = uniquify(os.getcwd(), outdir, title,
						start=chapnum, end=groupname)

		if not os.path.exists(dest_folder):
			os.makedirs(dest_folder)


		# download images
		for pagenum, url in enumerate(images, 1):
			filename = os.path.basename(url)
			ext = os.path.splitext(filename)[1]

			output_params = []
			output_params.append([pagenum, len(str(len(images))), len(images)])
			output_params.append([
						chapter["attributes"]["chapter"],
						chap_index,
						len(str(chap_amount)),
						chap_amount])
			if use_vols:
				output_params.append([current_vol,
					vol_index,
					len(str(vol_amount)),
					vol_amount])
				outfile = uniquify(dest_folder, start=chapnum,
						end=" p{}{}{}".format(
							zpad(str(pagenum)), groupname, ext))
			else:
				outfile = os.path.join(dest_folder, "{}{}".format(pagenum, ext))


			r = requests.get(url)
			# go back to the beginning and erase the line before printing more
			filled_output = [o.format(*p)
					for o, p in zip(output, output_params)]
			joined_output = " ".join(filled_output)
			bar_width = min(100, shutil.get_terminal_size((0,0)).columns-6)

			if bar_width > 0:
				print_bar(bar_width, page_index, page_amount)
				if len(joined_output) > bar_width:
					joined_output = "\n".join(filled_output)
					lines = len(output)
				else:
					lines = 1
			print(joined_output, end="", flush=True)

			if r.status_code == 200:
				with open(outfile, 'wb') as f:
					f.write(r.content)
			else:
				# silently try again
				time.sleep(2)
				r = requests.get(url)
				if r.status_code == 200:
					errored = False
					with open(outfile, 'wb') as f:
						f.write(r.content)
				else:
					errored = True
					print("\n Skipping download of page {} - error {}.".format(
						pagenum, r.status_code))

			time.sleep(0.2) # within limit of 5 requests per second
			# not reporting https://api.mangadex.network/report telemetry for now, sorry

			if not errored and bar_width > 0:
				print(lines*"\033[F"+"\033[J", end='') 
			page_index += 1

		if zip_up and (not use_vols or (use_vols
			and chapter # zip only at the end of volume
			== chap_list[vol_dict[current_vol][-1]])):
			zip_name = uniquify(os.getcwd(), outdir, title,
					start="{} {}".format(
						title, volnum if use_vols else chapnum),
					end="{}.cbz".format("" if use_vols else groupname))
			with zipfile.ZipFile(zip_name, 'w') as myzip:
				for root, dirs, files in os.walk(dest_folder):
					for file in files:
						path = os.path.join(root, file)
						myzip.write(path, os.path.basename(path))
			shutil.rmtree(dest_folder) # remove original folder of loose images
	print_bar(bar_width)
	print("\033[JDone.")


if __name__ == "__main__":
	print("mangadex-dl v{}".format(A_VERSION))

	parser = argparse.ArgumentParser()
	parser.add_argument("-l", dest="lang", required=False,
			action="store", default="en",
			help="download in specified language code (default: en)")
	parser.add_argument("-v", dest="volumes", required=False,
			action="store_true",
			help="select and sort by volumes rather than chapters "\
				"(assumes -s last)")
	parser.add_argument("-d", dest="datasaver", required=False,
			action="store_true",
			help="download images in lower quality")
	parser.add_argument("-a", dest="cbz", required=False,
			action="store_true",
			help="package chapters into .cbz format")
	parser.add_argument("-o", dest="outdir", required=False,
			action="store", default="download",
			help="specify name of output directory")
	same_chapter_choices = ["all","ask","first","last"]
	parser.add_argument("-s", dest="same_chapter_mode", required=False,
			action="store", default="all",
			metavar="|".join(same_chapter_choices),
			help="how to handle same numbered chapters "\
					"if not matched by group or user (default: all)",
			choices=same_chapter_choices)
	parser.add_argument("-g", dest="groups", required=False,
			action="store", metavar="GROUP[,...]",
			help="scanlation groups to prefer "\
					"in case of same numbered chapters")
	parser.add_argument("-u", dest="users", required=False,
			action="store", metavar="USER[,...]",
			help="uploaders to prefer "\
					"in case of same numbered chapters")
	args = parser.parse_args()

	lang_code = "en" if args.lang is None else str(args.lang)

	prefs = {}
	if args.users:
		prefs["users"] =  [s.strip() for s in args.users.split(",")]
	if args.groups:
		prefs["groups"] =  [s.strip() for s in args.groups.split(",")]
	if not args.same_chapter_mode:
		if volumes: same_chapter_mode = "last"
		else: same_chapter_mode = "all"
	else: same_chapter_mode = args.same_chapter_mode

	# prompt for manga
	url = ""
	while url == "":
		url = input("Enter manga URL or ID: ").strip()

	try:
		url_parts = url.split('/')
		manga_id = find_id_in_url(url_parts)
	except:
		print("Error with URL.")
		exit(1)

	dl(manga_id, lang_code, args.cbz, args.datasaver, args.outdir,
			args.volumes, same_chapter_mode, prefs)
