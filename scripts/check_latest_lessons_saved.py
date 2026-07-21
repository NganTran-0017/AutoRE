import os
import sys
import chromadb

#USAGE: python test/check_latest_lessons_saved.py [projectName]
# if no projectName is provided, the default_semantic database will be used as project name to search in memory folder
if __name__ == "__main__":
    # Check the latest lessons saved in the database
    REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if sys.argv and len(sys.argv) > 1:
        project_name = sys.argv[1]+'_semantic'
        max_lessons = int(sys.argv[2]) if len(sys.argv) > 2 else None
    else:
        project_name = 'default_semantic'
        max_lessons = None

    client = chromadb.PersistentClient(path=os.path.join(REPO_ROOT, 'memory', project_name))
    col = client.get_collection('lessons')                                                                             
    data = col.get(include=['metadatas', 'documents'])
    items = sorted(zip(data['ids'], data['metadatas'], data['documents']),
                    key=lambda x: x[1].get('timestamp', ''), reverse=True)
    for id_, meta, doc in items[:max_lessons]:
        print(id_, meta['timestamp'])
        print(doc)

#  Each lesson ID is formatted {agent}_{action}_{iteration}_{timestamp} (e.g. RE_UpdateAlloyModel_91_2026-07-03T11:43:50), so check whether an ID with the expected iteration number and timestamp shows up.