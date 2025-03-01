#!/usr/bin/env python

"""
Git command to automate many common tasks involving pull requests.

Usage:

	gitpr [<options>] <command> [<args>]

Options:

	-h, --help
		Display this message.

	-r <repo>, --repo <repo>
		Use this github repo instead of the 'remote origin' or 'github.repo'
		git config setting. This can be either a remote name or a full
		repository name (user/repo).

	-u <reviewer>, --reviewer <reviewer>
		Send pull requests to this github repo instead of the 'remote upstream'
		or 'github.reviewer' git config setting. This can be either a username
		or a full repository name (user/repo).

	-b <branch>, --update-branch <branch>
		Specify the target branch on the reviewer github repository to submit the pull request.

Commands:

	#no command#
		Displays a list of the open pull requests on this repository.

	#no command# <pull request ID>
		Performs a fetch.

	close [<comment>]
		Closes the current pull request on github and deletes the pull request
		branch.

	continue-update, cu
		Continues the current update after conflicts have been fixed.

	fetch <pull request ID>
		Fetches the pull request into a local branch, optionally updating it
		and checking it out.

	fetch-all
		Fetches all open pull requests into local branches.

	help
		Displays this message.

	info
		Displays a list of all the user's github repositories and the number
		of pull requests open on each.

	info-detailed
		Displays the same information as "info" but also lists the pull requests for each one (by user)

	merge
		Merges the current pull request branch into the update-branch and deletes the
		branch.

	open [<pull request ID>]
		Opens either the current pull request or the specified request on
		github.

	pull
		Pulls remote changes from the other user's remote branch into the local
		pull request branch.

	stats
		Fetches all open pull requests on this repository and displays them along
		with statistics about the pull requests and how many changes (along with how many
		changes by type).

	submit [<pull body>] [<pull title>]
		Pushes a branch and sends a pull request to the user's reviewer on
		github.

	update [<pull request ID or branch name>]
		Updates the current pull request or the specified request with the local
		changes in the update-branch, using either a rebase or merge.

Copyright (C) 2011 Liferay, Inc. <http://liferay.com>

Based on scripts by:
Connor McKay<connor.mckay@liferay.com>
Andreas Gohr <andi@splitbrain.org>
Minhchau Dang<minhchau.dang@liferay.com>
Nate Cavanaugh<nathan.cavanaugh@liferay.com>

Released under the MIT License.
"""

import base64
import getopt
import json
import os
import re
import sys
import urllib
import urllib2
# import isodate
# from datetime import date

# Connecting through a proxy,
# requires: socks.py from http://socksipy.sourceforge.net/ next to this file

#import socket
#import socks

#socks.setdefaultproxy(socks.PROXY_TYPE_SOCKS5, "localhost", 8181)
#socket.socket = socks.socksocket

from textwrap import fill

options = {
	# Color Scheme
	'color-success': 'green',
	'color-status': 'blue',
	'color-error': 'red',
	'color-warning': 'red',
	'color-display-title-url': 'cyan',
	'color-display-title-number': 'magenta',
	'color-display-title-text': 'red',
	'color-display-title-user': 'blue',
	'color-display-info-repo-title': 'default',
	'color-display-info-repo-count': 'magenta',
	'color-display-info-total-title': 'green',
	'color-display-info-total-count': 'magenta',

	# Disable the color scheme
	'enable-color': True,

	# Sets the default comment to post when closing a pull request.
	'close-default-comment': None,

	# Determines whether fetch will automatically checkout the new branch.
	'fetch-auto-checkout': False,

	# Determines whether to automatically update a fetched pull request branch.
	# Setting this option to true will also cause the new branch to be checked
	# out.
	'fetch-auto-update': False,

	# Whether to show pull requests for the entire repo or just the update-branch.
	'filter-by-update-branch': True,

	# Determines whether to automatically close pull requests after merging
	# them.
	'merge-auto-close': True,

	# Sets the branch to use where updates are merged from or to.
	'update-branch': 'master',

	# Sets the method to use when updating pull request branches with changes
	# in the update-branch.
	# Possible options: 'merge', 'rebase'
	'update-method': 'merge',

	# Determines whether to open newly submitted pull requests on github
	'submit-open-github': True,

	# Sets a directory to be used for performing updates to prevent
	# excessive rebuilding by IDE's. Warning: This directory will be hard reset
	# every time an update is performed, so do not do any work other than
	# conflict merges in the work directory.
	'work-dir': None
}

#print json.dumps(data,sort_keys=True, indent=4)

def authorize_request(req):
	"""Add the Authorize header to the request"""

	req.add_header("Authorization", "Basic %s" % auth_string)

def build_branch_name(pull_request):
	"""Returns the local branch name that a pull request should be fetched into"""
	ref = pull_request['head']['ref']

	request_id = pull_request['number']

	m = re.search("[A-Z]{3,}-\d+", ref)

	branch_name = 'pull-request-%s' % request_id

	if m != None and m.group(0) != '':
		branch_name = '%s-%s' % (branch_name, m.group(0))

	return branch_name

def build_pull_request_title(branch_name):
	"""Returns the default title to use for a pull request for the branch with
	the name"""

	m = re.search("([A-Z]{3,}-\d+)", branch_name)

	if m is not None and m.group(1) != '':
		return m.group(1)

	return branch_name

def chdir(dir):
	f = open('/tmp/git-pull-request-chdir', 'wb')
	f.write(dir)
	f.close()

def close_pull_request(repo_name, pull_request_ID, comment = None):
	if comment is None:
		comment = options['close-default-comment']

	try:
		f = open('/tmp/git-pull-request-treeish-%s' % pull_request_ID, 'rb')
		branch_treeish = f.read()
		f.close()

		if comment is None:
			comment = ''

		comment += "\n\nOriginal commits: %s" % branch_treeish
	except IOError:
		pass

	if comment is not None and comment != '':
		post_comment(repo_name, pull_request_ID, comment)

	url = "http://github.com/api/v2/json/issues/close/%s/%s" % (repo_name, pull_request_ID)
	github_json_request(url)

def color_text(text, token, bold = False):
	"""Return the given text in ANSI colors"""

	# http://travelingfrontiers.wordpress.com/2010/08/22/how-to-add-colors-to-linux-command-line-output/

	if options['enable-color'] == True:
		color_name = options["color-%s" % token]

		if color_name == 'default' or not sys.stdout.isatty():
			return text

		colors = (
			'black', 'red', 'green', 'yellow',
			'blue', 'magenta', 'cyan', 'white'
		)

		if color_name in colors:
			return u"\033[{0};{1}m{2}\033[0m".format(
				int(bold),
				colors.index(color_name) + 30,
				text)
		else:
			return text
	else:
		return text

def command_fetch(repo_name, pull_request_ID, auto_update = False):
	"""Fetches a pull request into a local branch"""

	print color_text("Fetching pull request", 'status')
	print

	pull_request = get_pull_request(repo_name, pull_request_ID)
	display_pull_request(pull_request)
	branch_name = fetch_pull_request(pull_request)

	if auto_update:
		update_branch(branch_name)
	elif options['fetch-auto-checkout']:
		ret = os.system('git checkout %s' % branch_name)
		if ret != 0:
			raise UserWarning("Could not checkout %s" % branch_name)

	print
	print color_text("Fetch completed", 'success')
	print
	display_status()

def command_close(repo_name, comment = None):
	"""Closes the current pull request on github with the optional comment, then
	deletes the branch."""

	print color_text("Closing pull request", 'status')
	print

	branch_name = get_current_branch_name()
	pull_request_ID = get_pull_request_ID(branch_name)
	pull_request = get_pull_request(repo_name, pull_request_ID)

	display_pull_request(pull_request)

	close_pull_request(repo_name, pull_request_ID, comment)

	update_branch_option = options['update-branch']

	ret = os.system('git checkout %s' % update_branch_option)
	if ret != 0:
		raise UserWarning("Could not checkout %s" % update_branch_option)

	print color_text("Deleting branch %s" % branch_name, 'status')
	ret = os.system('git branch -D %s' % branch_name)
	if ret != 0:
		raise UserWarning("Could not delete branch")

	print
	print color_text("Pull request closed", 'success')
	print
	display_status()

def command_continue_update():
	print color_text("Continuing update from %s" % options['update-branch'], 'status')

	continue_update()
	print
	display_status()

def command_fetch_all(repo_name):
	"""Fetches all pull requests into local branches"""

	print color_text("Fetching all pull requests", 'status')
	print

	pull_requests = get_pull_requests(repo_name, options['filter-by-update-branch'])

	for pull_request in pull_requests:
		fetch_pull_request(pull_request)
		display_pull_request_minimal(pull_request)
		print

	display_status()

def command_help():
	print __doc__

def command_info(username, detailed = False):
	print color_text("Loading information on repositories for %s" % username, 'status')
	print

	url = "http://github.com/api/v2/json/repos/show/%s" % username
	data = github_json_request(url)
	repos = data['repositories']
	# print json.dumps(data,sort_keys=True, indent=4)
	total = 0

	for pull_request_info in repos:
		issue_count = pull_request_info['open_issues']

		if issue_count > 0:
			base_name = pull_request_info['name']
			repo_name = "%s/%s" % (pull_request_info['owner'], base_name)

			print "  %s: %s" % (color_text(base_name, 'display-info-repo-title'), color_text(issue_count, 'display-info-repo-count'))

			if detailed:
				pull_requests = get_pull_requests(repo_name, options['filter-by-update-branch'])

				for pull_request in pull_requests:
					name = (pull_request['user'].get('name') or pull_request['user'].get('login')).encode('utf-8')
					print "    %s by %s" % (color_text("REQ %s" % pull_request.get('number'), 'display-title-number', True), color_text(name, 'display-title-user'))

			total += issue_count

	print "-"
	out = "%s: %s" % (color_text("Total pull requests", 'display-info-total-title', True), color_text(total, 'display-info-total-count', True))
	print
	display_status()
	return out

def command_merge(repo_name, comment = None):
	"""Merges changes from the local pull request branch into the update-branch and deletes
	the pull request branch"""

	branch_name = get_current_branch_name()
	pull_request_ID = get_pull_request_ID(branch_name)

	update_branch_option = options['update-branch']

	print color_text("Merging %s into %s" % (branch_name, update_branch_option), 'status')
	print

	ret = os.system('git checkout %s' % update_branch_option)
	if ret != 0:
		raise UserWarning("Could not checkout %s" % update_branch_option)

	ret = os.system('git merge %s' % branch_name)
	if ret != 0:
		raise UserWarning("Merge with %s failed. Resolve conflicts, switch back into the pull request branch, and merge again" % update_branch_option)

	print color_text("Deleting branch %s" % branch_name, 'status')
	ret = os.system('git branch -D %s' % branch_name)
	if ret != 0:
		raise UserWarning("Could not delete branch")

	if options['merge-auto-close']:
		print color_text("Closing pull request", 'status')
		close_pull_request(repo_name, pull_request_ID, comment)

	print
	print color_text("Merge completed", 'success')
	print
	display_status()

def command_open(repo_name, pull_request_ID = None):
	"""Open a pull request in the browser"""

	if pull_request_ID is None:
		branch_name = get_current_branch_name()
		pull_request_ID = get_pull_request_ID(branch_name)

	pull_request = get_pull_request(repo_name, pull_request_ID)

	open_URL(pull_request.get('html_url'))

def command_show(repo_name):
	"""List open pull requests

	Queries the github API for open pull requests in the current repo.
	"""

	update_branch_name = options['update-branch']
	filter_by_update_branch = options['filter-by-update-branch']

	if not filter_by_update_branch:
		update_branch_name = "across all branches"
	else:
		update_branch_name = "on branch '%s'" % update_branch_name

	print color_text("Loading open pull requests for %s %s" % (repo_name, update_branch_name), 'status')
	print

	pull_requests = get_pull_requests(repo_name, filter_by_update_branch)

	if len(pull_requests) == 0:
		print "No open pull requests found"

	for pull_request in pull_requests:
		display_pull_request(pull_request)

	display_status()

def get_pr_stats(repo_name, pull_request_ID):
	if pull_request_ID != None:
		is_int = False
		try:
			pull_request_ID = int(pull_request_ID)
			pull_request = get_pull_request(repo_name, pull_request_ID)
		except Exception, e:
			pull_request = pull_request_ID

		display_pull_request_minimal(pull_request)

		branch_name = build_branch_name(pull_request)
		ret = os.system('git show-ref --verify -q refs/heads/%s' % branch_name)

		if ret != 0:
			branch_name = fetch_pull_request(pull_request)

			ret = os.system('git show-ref --verify -q refs/heads/%s' % branch_name)

			if  ret != 0:
				raise UserWarning("Fetch failed")

		merge_base = os.popen('git merge-base %s %s' % (options['update-branch'], branch_name)).read().strip()
		ret = os.system("git --no-pager diff --shortstat {0}..{1} && git diff --numstat --pretty='%H' --no-renames {0}..{1} | xargs -0n1 echo -n | awk '{{print $3}}' | sed -e 's/^.*\.\(.*\)$/\\1/' | sort | uniq -c | tr '\n' ',' | sed 's/,$//'".format(merge_base, branch_name))
		print
	else:
		pull_requests = get_pull_requests(repo_name, options['filter-by-update-branch'])

		for pull_request in pull_requests:
			get_pr_stats(repo_name, pull_request)

def command_submit(repo_name, username, reviewer_repo_name = None, pull_body = None, pull_title = None, submitOpenGitHub = True):
	"""Push the current branch and create a pull request to your github reviewer
	(or upstream)"""

	branch_name = get_current_branch_name(False)

	print color_text("Submitting pull request for %s" % branch_name, 'status')

	if reviewer_repo_name is None or reviewer_repo_name == '':
		reviewer_repo_name = get_repo_name_for_remote('upstream')

	if reviewer_repo_name is None or reviewer_repo_name == '':
		raise UserWarning("Could not determine a repo to submit this pull request to")

	if '/' not in reviewer_repo_name:
		reviewer_repo_name = repo_name.replace(username, reviewer_repo_name)

	print color_text("Pushing local branch %s to origin" % branch_name, 'status')

	ret = os.system('git push origin %s' % branch_name)

	if ret != 0:
		raise UserWarning("Could not push this branch to your origin")

	url = "http://github.com/api/v2/json/pulls/%s" % reviewer_repo_name

	# pull[base] - A String of the branch or commit SHA that you want your changes to be pulled to.
	# pull[head] - A String of the branch or commit SHA of your changes. Typically this will be a branch. If the branch is in a fork of the original repository, specify the username first: "my-user:some-branch".
	# pull[title] - The String title of the Pull Request (and the related Issue).
	# pull[body] - The String body of the Pull Request.

	if pull_title == None or pull_title == '':
		pull_title = build_pull_request_title(branch_name)

	if pull_body == None:
		pull_body = ''
		# pull_body = raw_input("Comment: ").strip()

	params = {
		'pull[base]': options['update-branch'],
		'pull[head]': "%s:%s" % (username, branch_name),
		'pull[title]': pull_title,
		'pull[body]': pull_body
	}

	print color_text("Sending pull request to %s" % reviewer_repo_name, 'status')

	data = github_json_request(url, params)

	pull_request = data['pull']

	print
	display_pull_request(pull_request)
	print

	print color_text("Pull request submitted", 'success')
	print
	display_status()

	if submitOpenGitHub:
		open_URL(pull_request.get('html_url'))

def command_update(repo_name, target = None):
	if target == None:
		branch_name = get_current_branch_name()
	else:
		try:
			pull_request_ID = int(target)
			pull_request = get_pull_request(repo_name, pull_request_ID)
			branch_name = build_branch_name(pull_request)
		except ValueError:
			branch_name = target

	print color_text("Updating %s from %s" % (branch_name, options['update-branch']), 'status')

	update_branch(branch_name)
	print
	display_status()

def command_pull(repo_name):
	"""Pulls changes from the remote branch into the local branch of the pull
	request"""

	branch_name = get_current_branch_name()

	print color_text("Pulling remote changes into %s" % branch_name, 'status')

	pull_request_ID = get_pull_request_ID(branch_name)

	pull_request = get_pull_request(repo_name, pull_request_ID)
	repo_url = get_repo_url(pull_request)

	print color_text("Pulling from %s (%s)" % (repo_url, pull_request['head']['ref']), 'status')

	ret = os.system('git pull %s %s' % (repo_url, pull_request['head']['ref']))
	if ret != 0:
		raise UserWarning("Pull failed, resolve conflicts")

	print
	print color_text("Updating %s from remote completed" % branch_name, 'success')
	print
	display_status()

def complete_update(branch_name):
	update_branch_option = options['update-branch']

	if in_work_dir():
		ret = os.system('git checkout %s' % update_branch_option)
		if ret != 0:
			raise UserWarning("Could not checkout %s branch in work directory" % update_branch_option)

		original_dir_path = get_original_dir_path()

		print color_text("Switching to original directory: '%s'" % original_dir_path, 'status')

		os.chdir(original_dir_path)
		chdir(original_dir_path)

		if get_current_branch_name(False) == branch_name:
			ret = os.system('git reset --hard && git clean -f')
			if ret != 0:
				raise UserWarning("Syncing branch %s with work directory failed" % branch_name)
		else:
			ret = os.system('git checkout %s' % branch_name)
			if ret != 0:
				raise UserWarning("Could not checkout %s" % branch_name)

	print
	print color_text("Updating %s from %s complete" % (branch_name, update_branch_option), 'success')

def continue_update():
	if options['update-method'] == 'merge':
		ret = os.system('git commit')
	elif options['update-method'] == 'rebase':
		ret = os.system('git rebase --continue')

	if ret != 0:
		raise UserWarning("Updating from %s failed\nResolve conflicts and 'git add' files, then run 'gitpr continue-update'" % options['update-branch'])

	# The branch name will not be correct until the merge/rebase is complete
	branch_name = get_current_branch_name()

	complete_update(branch_name)

def display_pull_request(pull_request):
	"""Nicely display_pull_request info about a given pull request"""

	display_pull_request_minimal(pull_request)
	print "	%s" % color_text(pull_request.get('html_url'), 'display-title-url')

	# print json.dumps(pull_request,sort_keys=True, indent=4)
	if pull_request.get('body').strip():
		print fill(pull_request.get('body'), initial_indent="	", subsequent_indent="	", width=80)

	# print "   Created: %s" % date.strftime(isodate.parse_datetime( pull_request.get('issue_created_at')), "%B %d, %Y at %I:%M %p")
	# print "   Created: %s" % pull_request.get('issue_created_at')
	# print isodate.parse_datetime( pull_request.get('issue_created_at'), "%Y-%m-%dT%H:%M:%S" )

	print

def display_pull_request_minimal(pull_request):
	"""Display minimal info about a given pull request"""

	print "%s - %s by %s (%s)" % (color_text("REQUEST %s" % pull_request.get('number'), 'display-title-number', True), color_text(pull_request.get('title'), 'display-title-text', True), color_text(pull_request['user'].get('name'), 'display-title-user'), pull_request['user'].get('login'))

def display_status():
	"""Displays the current branch name"""

	branch_name = get_current_branch_name(False)
	out = "Current branch: %s" % branch_name
	print out
	return out

def fetch_pull_request(pull_request):
	"""Fetches a pull request into a local branch, and returns the name of the
	local branch"""

	branch_name = build_branch_name(pull_request)
	repo_url = get_repo_url(pull_request)

	remote_branch_name = pull_request['head']['ref']


	# print json.dumps(pull_request,sort_keys=True, indent=4)

	ret = os.system('git fetch %s %s:%s' % (repo_url, remote_branch_name, branch_name))

	if ret != 0:
		ret = os.system('git show-ref --verify refs/heads/%s' % branch_name)

	if ret != 0:
		raise UserWarning("Fetch failed")

	try:
		os.remove('/tmp/git-pull-request-treeish-%s' % pull_request['number'])
	except OSError:
		pass

	return branch_name

def get_current_branch_name(ensure_pull_request = True):
	"""Returns the name of the current pull request branch"""
	branch_name = os.popen('git rev-parse --abbrev-ref HEAD').read().strip()

	if ensure_pull_request and branch_name[0:13] != 'pull-request-':
		raise UserWarning("Invalid branch: not a pull request")

	return branch_name

def get_default_repo_name():
	repo_name = os.popen('git config github.repo').read().strip()

	# get repo name from origin
	if repo_name is None or repo_name == '':
		repo_name = get_repo_name_for_remote('origin')

	if repo_name is None or repo_name == '':
		raise UserWarning("Failed to determine github repository name")

	return repo_name

def get_git_base_path():
	return os.popen('git rev-parse --show-toplevel').read().strip()

def get_original_dir_path():
	git_base_path = get_git_base_path()

	f = open(os.path.join(get_work_dir(), '.git', 'original_dir_path'), 'rb')
	original_dir_path = f.read()
	f.close()

	if original_dir_path == None or original_dir_path == '':
		config_path = os.readlink(os.path.join(git_base_path, '.git', 'config'))
		original_dir_path = os.path.dirname(os.path.dirname(config_path))

	return original_dir_path

def get_work_dir():
	global _work_dir

	if (_work_dir == None):
		symbolic_ref = os.popen('git symbolic-ref HEAD').read().strip().replace('refs/heads/', '')
		work_dir_global = options['work-dir']

		work_dir_option = None

		if symbolic_ref:
			work_dir_option = 'work-dir-%s' % symbolic_ref

		if work_dir_option:
			_work_dir = os.popen('git config git-pull-request.%s' % work_dir_option).read().strip()
			options[work_dir_option] = _work_dir

		if not os.path.exists(_work_dir):
			_work_dir = False

		if not _work_dir:
			if work_dir_global and os.path.exists(work_dir_global):
				_work_dir = work_dir_global
			else:
				_work_dir = False

	return _work_dir

def get_pull_request(repo_name, pull_request_ID):
	"""Returns information retrieved from github about the pull request"""

	url = "http://github.com/api/v2/json/pulls/%s/%s" % (repo_name, pull_request_ID)
	data = github_json_request(url)

	return data['pull']

def get_pull_requests(repo_name, filter_by_update_branch=False):
	"""Returns information retrieved from github about the open pull requests on
	the repository"""

	url = "http://github.com/api/v2/json/pulls/%s/open" % repo_name
	data = github_json_request(url)
	pulls = data['pulls']

	if filter_by_update_branch:
		update_branch = options['update-branch']

		pull_requests = [pull for pull in pulls if pull['base']['ref'] == update_branch]
	else:
		pull_requests = pulls

	return pull_requests

def get_pull_request_ID(branch_name):
	"""Returns the pull request number of the branch with the name"""

	m = re.search("^pull-request-(\d+)", branch_name)

	return int(m.group(1))

def get_repo_name_for_remote(remote_name):
	"""Returns the repository name for the remote with the name"""

	remotes = os.popen('git remote -v').read()
	m = re.search("^%s[^\n]+?github\.com[^\n]*?[:/]([^\n]+?)\.git" % remote_name, remotes, re.MULTILINE)

	if m is not None and m.group(1) != '':
		return m.group(1)

def get_repo_url(pull_request):
	"""Returns the git URL of the repository the pull request originated from"""

	repo_url = pull_request['head']['repository']['url'].replace('https', 'git')
	private_repo = pull_request['head']['repository']['private']

	if private_repo:
		repo_url = repo_url.replace('git://github.com/', 'git@github.com:')

	return repo_url

def github_json_request(url, params = None):
	if params is not None:
		data = urllib.urlencode(params)
		req = urllib2.Request(url, data)
	else:
		req = urllib2.Request(url)

	authorize_request(req)

	print url

	try:
		response = urllib2.urlopen(req)
	except urllib2.URLError, msg:
		raise UserWarning("Error communicating with github: \n%s\n%s" % (url, msg))

	data = response.read()
	if data == '':
		raise UserWarning("Invalid response from github")

	data = json.loads(data)
	# print json.dumps(data,sort_keys=True, indent=4)
	return data

def in_work_dir():
	git_base_path = get_git_base_path()

	work_dir = get_work_dir()

	return git_base_path == work_dir and os.path.islink(os.path.join(git_base_path, '.git', 'config'))

def load_options():
	all_config = os.popen('git config -l').read().strip()
	git_base_path = os.popen('git rev-parse --show-toplevel').read().strip()

	path_prefix = "%s." % git_base_path

	overrides = {}

	matches = re.findall("^git-pull-request\.([^=]+)=([^\n]*)$", all_config, re.MULTILINE)

	for k in matches:
		key = k[0]
		value = k[1]

		if value.lower() in ('f', 'false', 'no'):
			value = False
		elif value.lower() in ('t', 'true', 'yes'):
			value = True
		elif value.lower() in ('', 'none', 'null', 'nil'):
			value = None

		if key.find(path_prefix) == -1:
			options[key] = value
		else:
			key = key.replace(path_prefix, '')
			overrides[key] = value

	options.update(overrides)

def main():
	# parse command line options
	try:
		opts, args = getopt.gnu_getopt(sys.argv[1:], 'hqar:u:l:b:', ['help', 'quiet', 'all', 'repo=', 'reviewer=', 'update', 'no-update', 'user=', 'update-branch='])
	except getopt.GetoptError, e:
		raise UserWarning("%s\nFor help use --help" % e)

	if len(args) > 0 and args[0] == 'help':
		command_help()
		sys.exit(0)

	# load git options
	load_options()

	global auth_string
	global _work_dir

	_work_dir = None

	repo_name = None
	reviewer_repo_name = None

	username = os.popen('git config github.user').read().strip()
	auth_token = os.popen('git config github.token').read().strip()

	if len(username) == 0:
		username = raw_input("Github username: ").strip()
		os.system("git config --global github.user %s" % username)

	if len(auth_token) == 0:
		print "Please go to https://github.com/account/admin to find your API token"
		auth_token = raw_input("Github API token: ").strip()
		os.system("git config --global github.token %s" % auth_token)

	auth_user = "%s/token" % username
	auth_string = base64.encodestring('%s:%s' % (auth_user, auth_token)).replace('\n', '')

	fetch_auto_update = options['fetch-auto-update']

	info_user = username
	submitOpenGitHub = options['submit-open-github']

	# process options
	for o, a in opts:
		if o in ('-h', '--help'):
			command_help()
			sys.exit(0)
		elif o in ('-l', '--user'):
			info_user = a
		elif o in ('-q', '--quiet'):
			submitOpenGitHub = False
		elif o in ('-a', '--all'):
			options['filter-by-update-branch'] = False
		elif o in ('-r', '--repo'):
			if re.search('/', a):
				repo_name = a
			else:
				repo_name = get_repo_name_for_remote(a)
		elif o in ('-b', '--update-branch'):
			options['update-branch'] = a
		elif o in ('-u', '--reviewer'):
			reviewer_repo_name = a
		elif o == '--update':
			fetch_auto_update = True
		elif o == '--no-update':
			fetch_auto_update = False

	# get repo name from git config
	if repo_name is None or repo_name == '':
		repo_name = get_default_repo_name()

	if reviewer_repo_name is None or reviewer_repo_name == '':
		reviewer_repo_name = os.popen('git config github.reviewer').read().strip()

	# process arguments
	if len(args) > 0:
		if args[0] == 'close':
			if len(args) >= 2:
				command_close(repo_name, args[1])
			else:
				command_close(repo_name)
		elif args[0] in ('continue-update', 'cu'):
			command_continue_update()
		elif args[0] == 'fetch':
			command_fetch(repo_name, args[1], fetch_auto_update)
		elif args[0] == 'fetch-all':
			command_fetch_all(repo_name)
		elif args[0] == 'help':
			command_help()
		elif args[0] == 'info':
			command_info(info_user)
		elif args[0] == 'info-detailed':
			command_info(info_user, True)
		elif args[0] == 'merge':
			if len(args) >= 2:
				command_merge(repo_name, args[1])
			else:
				command_merge(repo_name)
		elif args[0] == 'open':
			if len(args) >= 2:
				command_open(repo_name, args[1])
			else:
				command_open(repo_name)
		elif args[0] == 'pull':
			command_pull(repo_name)
		elif args[0] == 'submit':
			pull_body = None
			pull_title = None

			if len(args) >= 2:
				pull_body = args[1]

			if len(args) >= 3:
				pull_title = args[2]

			command_submit(repo_name, username, reviewer_repo_name, pull_body, pull_title, submitOpenGitHub)
		elif args[0] == 'update':
			if len(args) >= 2:
					command_update(repo_name, args[1])
			else:
				command_update(repo_name)
		elif args[0] == 'stats' or args[0] == 'stat':
			pull_request_ID = None

			if len(args) >= 2:
				pull_request_ID = args[1]

			get_pr_stats(repo_name, pull_request_ID)
		else:
			command_fetch(repo_name, args[0], fetch_auto_update)
	else:
		command_show(repo_name)

def open_URL(url):
	if (os.popen('command -v open').read().strip() != ''):
		ret = os.system('open -g "%s" 2>/dev/null' % url)

		if ret != 0:
			os.system('open "%s"' % url)

	elif (os.popen('command -v cygstart').read().strip() != ''):
		os.system('cygstart "%s"' % url)

def post_comment(repo_name, pull_request_ID, comment):
	url = "http://github.com/api/v2/json/issues/comment/%s/%s" % (repo_name, pull_request_ID)
	params = {'comment': comment}
	github_json_request(url, params)

def update_branch(branch_name):
	if in_work_dir():
		raise UserWarning("Cannot perform an update from within the work directory.\nIf you are done fixing conflicts run 'gitpr continue-update' to complete the update.")

	work_dir = get_work_dir()

	if work_dir:
		original_dir_path = get_git_base_path()

		print color_text("Switching to work directory %s" % work_dir, 'status')
		os.chdir(work_dir)

		f = open(os.path.join(work_dir, '.git', 'original_dir_path'), 'wb')
		f.write(original_dir_path)
		f.close()

		ret = os.system('git reset --hard && git clean -f')
		if ret != 0:
			raise UserWarning("Cleaning up work directory failed, update not performed")

	ret = os.system('git checkout %s' % branch_name)
	if ret != 0:
		if work_dir:
			raise UserWarning("Could not checkout %s in the work directory, update not performed" % branch_name)
		else:
			raise UserWarning("Could not checkout %s, update not performed" % branch_name)

	update_branch_option = options['update-branch']

	parent_commit = os.popen('git merge-base %s %s' % (update_branch_option, branch_name)).read().strip()
	head_commit = os.popen('git rev-parse HEAD').read().strip()

	if parent_commit == head_commit:
		branch_treeish = head_commit[0:10]
	else:
		branch_treeish = '%s..%s' % (parent_commit[0:10], head_commit[0:10])

	pull_request_ID = get_pull_request_ID(branch_name)
	f = open('/tmp/git-pull-request-treeish-%s' % pull_request_ID, 'wb')
	f.write(branch_treeish)
	f.close()

	print color_text("Original commits: %s" % branch_treeish, 'status')

	ret = os.system('git %(update-method)s %(update-branch)s' % (options))

	if ret != 0:
		if work_dir:
			chdir(work_dir)
		raise UserWarning("Updating %s from %s failed\nResolve conflicts and 'git add' files, then run 'gitpr continue-update'" % (branch_name, update_branch_option))

	complete_update(branch_name)


def log(*args):
	for arg in args:
		print json.dumps(arg, sort_keys=True, indent=4)
		print "/---"

if __name__ == "__main__":
	try:
		main()
	except UserWarning, e:
		print color_text(e, 'error')
		sys.exit(1)
