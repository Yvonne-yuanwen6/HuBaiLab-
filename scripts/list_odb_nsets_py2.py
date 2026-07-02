# -*- coding: utf-8 -*-
from odbAccess import openOdb
import sys
odb = openOdb(path=sys.argv[1], readOnly=1)
assembly = odb.rootAssembly
for k in sorted(assembly.nodeSets.keys()):
    ns = assembly.nodeSets[k]
    print(k, len(ns.nodes))
odb.close()
