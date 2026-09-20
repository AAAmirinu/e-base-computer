import json
import sys
from production_normal_permission import prepare,inspect

if __name__=='__main__':
    if sys.argv[1:]==['--prepare']:result=prepare()
    elif sys.argv[1:]==['--inspect']:result=inspect()
    else:raise ValueError('Fixed Normal permission evidence action required')
    print(json.dumps(result,sort_keys=True),flush=True)
