import json,subprocess,sys,datetime as dt,concurrent.futures as cf
Q='''query($q:String!,$cur:String){search(query:$q,type:ISSUE,first:50,after:$cur){pageInfo{hasNextPage endCursor}
 nodes{... on Issue{number title createdAt state author{login} labels(first:20){nodes{name}}
  timelineItems(first:60,itemTypes:[LABELED_EVENT,UNLABELED_EVENT,ASSIGNED_EVENT,UNASSIGNED_EVENT]){nodes{__typename
   ... on LabeledEvent{createdAt label{name} actor{login}} ... on UnlabeledEvent{createdAt label{name} actor{login}}
   ... on AssignedEvent{createdAt actor{login} assignee{... on User{login}}} ... on UnassignedEvent{createdAt actor{login} assignee{... on User{login}}}}}}}}}'''
def week(start):
    end=start+dt.timedelta(days=3); q=f"repo:microsoft/vscode is:issue created:{start}..{end-dt.timedelta(days=1)}"; cur=None; out=[]
    while True:
        r=subprocess.run(["gh","api","graphql","-f",f"query={Q}","-f",f"q={q}"]+(["-f",f"cur={cur}"] if cur else []),capture_output=True,text=True)
        try: d=json.loads(r.stdout)["data"]["search"]
        except Exception: print("err",start,r.stdout[:150],file=sys.stderr); break
        out+=[n for n in d["nodes"] if n]
        if not d["pageInfo"]["hasNextPage"]: break
        cur=d["pageInfo"]["endCursor"]
    return out
starts=[dt.date(2026,6,1)+dt.timedelta(days=3*i) for i in range(45)]
with cf.ThreadPoolExecutor(4) as ex: R=list(ex.map(week,starts))
allI=[i for w in R for i in w]
json.dump(allI,open("vscode_all.json","w")); print("issues:",len(allI))
