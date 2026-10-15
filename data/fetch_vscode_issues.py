import json,subprocess,sys,datetime as dt,concurrent.futures as cf
Q='''query($q:String!,$cur:String){search(query:$q,type:ISSUE,first:50,after:$cur){pageInfo{hasNextPage endCursor}
 nodes{... on Issue{number title createdAt state author{login} labels(first:20){nodes{name}}
  timelineItems(first:60,itemTypes:[LABELED_EVENT,UNLABELED_EVENT,ASSIGNED_EVENT,UNASSIGNED_EVENT]){nodes{__typename
   ... on LabeledEvent{createdAt label{name} actor{login}} ... on UnlabeledEvent{createdAt label{name} actor{login}}
   ... on AssignedEvent{createdAt actor{login} assignee{... on User{login}}} ... on UnassignedEvent{createdAt actor{login} assignee{... on User{login}}}}}}}}}'''
def week(start):
    end=min(start+dt.timedelta(days=3),END+dt.timedelta(days=1)); q=f"repo:microsoft/vscode is:issue created:{start}..{end-dt.timedelta(days=1)}"; cur=None; out=[]
    while True:
        r=subprocess.run(["gh","api","graphql","-f",f"query={Q}","-f",f"q={q}"]+(["-f",f"cur={cur}"] if cur else []),capture_output=True,text=True)
        try: d=json.loads(r.stdout)["data"]["search"]
        except Exception: print("err",start,r.stdout[:150],file=sys.stderr); break
        out+=[n for n in d["nodes"] if n]
        if not d["pageInfo"]["hasNextPage"]: break
        cur=d["pageInfo"]["endCursor"]
    return out
START=dt.date.fromisoformat(sys.argv[1]); END=dt.date.fromisoformat(sys.argv[2]); OUT=sys.argv[3]
starts=[START+dt.timedelta(days=3*i) for i in range((END-START).days//3+1)]
with cf.ThreadPoolExecutor(4) as ex: R=list(ex.map(week,starts))
allI=[i for w in R for i in w]
json.dump(allI,open(OUT,"w")); print("issues:",len(allI))
