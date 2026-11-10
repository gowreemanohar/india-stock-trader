"""Read-only inventory of original installed skills; never imports or executes them."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
from pack_core import write_json


def inventory(root):
    result=[]
    for folder in sorted(Path(root).glob('trader-*')):
        for file in sorted(folder.glob('*')):
            if not file.is_file() or file.suffix not in ('.py','.md','.json'):
                continue
            raw=file.read_bytes()
            item={'file':str(file),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
            if file.suffix=='.py':
                tree=ast.parse(raw.decode('utf-8-sig'))
                commands=[];flags=[]
                for node in ast.walk(tree):
                    if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr in ('add_parser','add_argument'):
                        values=[a.value for a in node.args if isinstance(a,ast.Constant) and isinstance(a.value,str)]
                        (commands if node.func.attr=='add_parser' else flags).extend(values)
                item.update(commands=commands,arguments=list(dict.fromkeys(flags)),
                            functions=[n.name for n in tree.body if isinstance(n,ast.FunctionDef)],
                            imports=[ast.unparse(n) for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom))])
            result.append(item)
    return {'original_root':str(root),'upstream':'https://github.com/Jakeschincariol/day-trader-skill',
            'method':'All installed original Python parsed as AST; commands, flags, functions, imports and file SHA-256 recorded. No original script executed.',
            'files':result}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    result=inventory(args.root)
    write_json(args.output,result)
    print(json.dumps({'inventoried_files':len(result['files']),'output':args.output}))
