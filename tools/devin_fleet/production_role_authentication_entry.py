"""Fixed CLI for preparing or inspecting aggregate role authentication evidence."""
import json
import sys
from production_role_authentication import prepare,inspect

if __name__=='__main__':
    if sys.argv[1:]==['--prepare']:
        result=prepare()
    elif sys.argv[1:]==['--inspect']:
        result=inspect()
    else:
        raise ValueError('Fixed role authentication evidence action required')
    print(json.dumps(result,sort_keys=True),flush=True)
