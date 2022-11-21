from github import Github
import sys

g = None

def setup(*args, **kwargs):
    global g
    g = Github(*args, **kwargs)

def open_issue_on_failure(repo_name, title, body, tags):
    repo = g.get_repo(repo_name)
    body += '\n\n' + ' '.join(['@'+tag for tag in tags])
    return repo.create_issue(title, body).number

def resolve_issue(repo_name, issue_num):
    repo = g.get_repo(repo_name)
    issue = repo.get_issue(issue_num)
    issue.create_comment('This issue has been resolved!')
    issue.edit(state='closed')