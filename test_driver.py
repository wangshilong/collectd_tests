#!/usr/bin/python

import sys
import os
import time
import tempfile
import signal
import getopt
import shutil
from string import Template
try:
    import xml.etree.cElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET

hostname = os.uname()[1].split('.')[0]
collectd_dir = "/tmp/test"
pid_file = collectd_dir + "/" + "collectd.pid"
collectd_conf = "collectd.conf"
xml_path = ""
collectd_interval = 1
exit_on_error = 0


FATAL_MSG = 0
ERROR_MSG = 1
LOG_MSG = 2

def exit_test():
	if os.path.exists(pid_file):
		pf = open(pid_file, 'r')
		pid = int(pf.read().strip())
		os.kill(pid, signal.SIGTERM)

def receive_signal(signum, stack):
	exit_test()

def log(msg, level):
	print msg
	if level == LOG_MSG:
		return
	if exit_on_error == 1 or FATAL_MSG == level:
		exit_test()
		sys.exit(1)
usages = [
	"Help messages:",
	"	-h/--help",
	"	--exit_on_error exit if error happens",
	"	--xml_path specify lustre definition xml path",
]
def print_usages(ret):
	for line in usages:
		print line
	sys.exit(ret)

def parse_args():
	global xml_path
	try:
		options, args = getopt.getopt(sys.argv[1:], "hp:i:",
					      ["help", "xml_path=", "exit_on_error"])
	except getopt.GetoptError:
		print_usages(1)
	for name, value in options:
		if name in ("-h", "--help"):
			print_usages(0)
		if name in ("--exit_on_error"):
			exit_on_error = 1
		if name in ("--xml_path"):
			xml_path = value
	if xml_path == "":
		log("Please specify xml_path for this test", FATAL_MSG)

# parse agrs here to make top_lines assignment happy.
parse_args()

signal.signal(signal.SIGINT, receive_signal)
signal.signal(signal.SIGTERM, receive_signal)

top_lines = [
	"Interval " + str(collectd_interval),
	"LoadPlugin syslog",
	"<Plugin syslog>",
	"	Loglevel err",
	"</Plugin>",
	"LoadPlugin rrdtool",
	"<Plugin rrdtool>",
	"	Datadir " + '"' + collectd_dir + '"',
	"</Plugin>",
	"LoadPlugin lustre",
	'<Plugin "lustre">',
	"	<Common>",
	"		DefinitionFile " + '"' + xml_path + '"',
	"		Rootpath " + '"' + collectd_dir + '"',
	"	</Common>"
]

# generate collectd config according to xml
def generate_collectd_conf(xml_file):
	tree = ET.parse(xml_file)
	# find all item name.
	f = open(collectd_conf, 'w')
	for line in top_lines:
		f.write(line + "\n")
	for atype in tree.findall("entry"):
		for btype in atype.findall("item"):
			name = btype.find('name').text
			f.write("	<Item>\n")
			f.write("		Type %s\n" % ('"' + name + '"'))
			f.write("	</Item>\n")
	f.write("</Plugin>\n")
	f.close()

def is_exe(fpath):
	return os.path.isfile(fpath) and os.access(fpath, os.X_OK)

def which(program):
    fpath, fname = os.path.split(program)
    if fpath:
        if is_exe(program):
            return program
    else:
        for path in os.environ["PATH"].split(os.pathsep):
            path = path.strip('"')
            exe_file = os.path.join(path, program)
            if is_exe(exe_file):
                return exe_file
    return "None"

required_commands = [
	"collectd",
	"rrdtool",
]
def check_commands():
	for command in required_commands:
		if which(command) == "None":
			log("Fatal error command: %s not found" % (command), FATAL_MSG)

# this shoud be same for all rrd file?
def parse_rrd(rrdfile):
	x = ""
	fileTemp = tempfile.NamedTemporaryFile(delete = False)
	try:
		os.system("rrdtool dump %s > %s" % (rrdfile, fileTemp.name))
		per = ET.parse(fileTemp.name)
		p = per.find("/ds")
		for x in p:
			if x.tag == "last_ds":
				break
	finally:
		os.remove(fileTemp.name)
		num = x.text.strip()
		return num.split('.')[0]

def parse_xml(xml_file):
	tree = ET.parse(xml_file)
	for atype in tree.findall("entry"):
		content_path = atype.find('content_path').text
		content_type = atype.find('content_type').text
		content = atype.find('content').text
		content_path = collectd_dir + "/" + content_path
		if not os.path.exists(content_path):
			os.makedirs(os.path.dirname(content_path), 0755)
		if content_type == "external":
			shutil.copy2(os.path.dirname(xml_file) + "/" + content, content_path)
		else:
			print "deal with inline file here"
		# Let's relax and smoke here to wait collectd finish.
		time.sleep(collectd_interval * 2)
		for btype in atype.findall("item"):
			data_path = Template(btype.find('data_path').text)
			data_path = data_path.substitute(hostname=hostname)
			data_value = btype.find('data_value').text
			rrdfile = collectd_dir + "/" + data_path
			if not os.path.exists(rrdfile):
				log("Error: rrdfile: %s not exist" % (rrdfile), ERROR_MSG)
				continue
			content = parse_rrd(rrdfile)
			if content == data_value:
				log("PASS", LOG_MSG)
			else:
				log("ERROR: rrdfile: %s Expect: %s, Got: %s" % (rrdfile, data_value, content), ERROR_MSG)

def setup_test():
	if collectd_dir == "/":
		log("dangerous directory /", FATAL_MSG)
	if os.path.exists(collectd_dir):
		shutil.rmtree(collectd_dir,True)
		os.makedirs(collectd_dir, 0755)
	if os.system("collectd -C %s -P %s" % (collectd_conf, pid_file)) != 0:
		log("Failed to start collectd", FATAL_MSG)

def iterate_all_tests(rootdir):
	for dirName, subdirList, fileList in os.walk(rootdir):
		for fname in fileList:
			if fname.endswith("xml"):
				path = dirName + "/" + fname
				generate_collectd_conf(path)
				setup_test()
				parse_xml(path)
				exit_test()
check_commands()
iterate_all_tests("./tests")
