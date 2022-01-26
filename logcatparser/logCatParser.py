import os,sys,re, json
import argparse

LOG_LEVELS = {
	# according to http://developer.android.com/tools/debugging/debugging-log.html
	"V": "verbose",
	"D": "debug",
	"I": "info",
	"W": "warn",
	"E": "error",
	"A": "assert",
	"F": "fatal",
	"S": "silent"
}

ERROR_TYPES = {
	"NoRelease": r"Resource acquired .* not released",
	"Exception": "Exception occured during run",
	"ResourceLeak": "Resource has leaked",
	"NoProviderInfo": "Failed to find provider info",
	"ANR": "Application is not responding",
	"ProcessCrash": "process crashing",
	"JavaException": "Exception",
	"Unknown": "Not catalogued error",

}

def getFormatRegex(log_format):
		# https://developer.android.com/studio/command-line/logcat#outputFormat
		return {
			"threadtime": "^(\d{2}\-\d{2}) (\d\d:\d\d:\d\d\.\d+)\s*(\d+)\s*(\d+)\s([VDIWEAF])\s([^:]*):\s+(.*)?$",
			#"brief": "([VDIWEAF])\/([^)]{0,23})?\\(\\s*(?<pid>\\d+)\\):\\s+(?<message>.*)$"
		}[log_format]

class LogStats(object):
	def __init__(self):
		self.stats = {}
		self.levels = {}
		self.know_errors={}
		self.know_errors_indexes = {}
		for level in LOG_LEVELS.values():
			self.stats[level]=0
			self.levels[level]={}
		for erro in ERROR_TYPES.keys():
			self.know_errors[erro] = 0
			self.know_errors_indexes[erro] = set()

	def updateStat(self, obj, idx):
		if "level" not in obj:
			return
		self.stats[obj["level"]] += 1
		error_type = self.inferErrorType(obj)
		if error_type != "Unknown":
			self.know_errors[error_type] += 1
			self.know_errors_indexes[error_type].add(idx)

		if obj["tag"] in self.levels[obj["level"]]:
			self.levels[obj["level"]][obj["tag"]] += 1
		else:
			self.levels[obj["level"]][obj["tag"]] = 1


	def inferErrorType(self,obj):
		for e, m in ERROR_TYPES.items():
			if re.search(m, obj['message']) or m in str(obj['message']) :
				return e
		return "Unknown"


class LogCatParser(object):
	def __init__(self, log_format, filepath ):
		self.log_format = log_format
		self.format_regex = getFormatRegex(log_format)
		self.filepath = filepath
		self.parsedLines = []
		self.stats = LogStats()

	def mergeLines(self,line_obj_to_merge):
		self.parsedLines[-1]["message"] += "\n"+line_obj_to_merge["message"]

	def canMergeLines(self,log_line_obj):
		if len(self.parsedLines) == 0:
			return False
		last_parsed_line_id = self.getLogLineID( self.parsedLines[-1])
		return last_parsed_line_id == self.getLogLineID(log_line_obj)


	def getLogLineID(self,log_line_obj):
		date = "" if "date" not in log_line_obj else log_line_obj["date"]
		time = "" if "time" not in log_line_obj else log_line_obj["time"]
		pid = "" if "pid" not in log_line_obj else log_line_obj["pid"]
		tid = "" if "tid" not in log_line_obj else log_line_obj["tid"]
		level = "" if "level" not in log_line_obj else log_line_obj["level"]
		return date+time+pid+tid+level

	def buildLogLine(self, log_line_groups):
		log_obj = {}
		if self.log_format == "threadtime":
			log_obj['date'] = log_line_groups[0]
			log_obj['time'] = log_line_groups[1]
			log_obj['pid'] = log_line_groups[2]
			log_obj['tid'] = log_line_groups[3]
			log_obj['level'] = LOG_LEVELS[ log_line_groups[4] ]
			log_obj['tag'] = log_line_groups[5].strip()
			log_obj['message'] = log_line_groups[6]
		return log_obj

	def addParsedLine(self, parsed_obj):
		if self.canMergeLines(parsed_obj):
			self.mergeLines(parsed_obj)
		else:
			if len(self.parsedLines) > 0:
				self.stats.updateStat(self.parsedLines[-1], len(self.parsedLines)-1)
			self.parsedLines.append(parsed_obj)


	def parseFile(self):
		regex = getFormatRegex(self.log_format)
		f = open(self.filepath, "r")
		for  line in f.readlines():
			match = re.search("%s" % regex, line)
			if match:
				parsed_obj = self.buildLogLine(match.groups())
				self.addParsedLine(parsed_obj)
				self.stats.updateStat(parsed_obj, len(self.parsedLines)-1)

	def printParserInfo(self):
		obj = {"know_errors": self.stats.know_errors}
		for k,v in self.stats.levels.items():
			if len(v)>0:
				obj[k+"s"] = v
		obj["stats"] = self.stats.stats
		obj["logs"] = self.parsedLines
		print(json.dumps(obj, indent=1))

	def has_fatal_error(self):
		return self.stats.stats["fatal"] > 0

	def has_retrieve_know_error_from_pkg(self, pkg_name):
		log_errors = {}
		for error, idxs in self.stats.know_errors_indexes.items():
			for id in idxs:
				log_line_obj = self.parsedLines[id]
				if pkg_name in log_line_obj['message']:
					log_errors[error] = [] if not error in log_errors else log_errors[error]
					log_errors[error].append(log_line_obj)
		return log_errors if len(log_errors) > 0 else None

	def has_know_error_from_pkg(self, pkg_name):
		for error, idxs in self.stats.know_errors_indexes.items():
			for id in idxs:
				log_line_obj = self.parsedLines[id]
				if pkg_name in log_line_obj['message']:
					return True
		return False

	def get_logs_of_level(self, level="error"):
		if level not in LOG_LEVELS.values():
			print(f"error. level \"{level}\" not in {LOG_LEVELS.values()}")
			return []
		return list(filter(lambda x: x['level'] == level, self.parsedLines))

	def get_logs_of_error(self, error):
		if error not in ERROR_TYPES.keys():
			print(f"error. error \"{error}\" not in {ERROR_TYPES.keys()}")
			return []
		return list(map(lambda x: self.parsedLines[x], self.stats.know_errors_indexes[error]))

def main():
	parser = argparse.ArgumentParser()
	parser.add_argument('path', metavar='path', type=str, help='filepath')
	parser.add_argument("-f", "--format", type=str, help="provide log format", default="threadtime", choices=['threadtime'])
	parser.add_argument("-o", "--output", type=str, help="output format", choices=["json"])
	args = parser.parse_args()
	parser = LogCatParser(args.format, args.path)
	parser.parseFile()
	print(parser.get_logs_of_level("error"))

if __name__ == "__main__":
		main()
