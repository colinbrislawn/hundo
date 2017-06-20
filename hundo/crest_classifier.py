"""
Code modified from CREST v3.0.

Written by: Lanzén A , Jørgensen SL, Huson D, Gorfer M, Grindhaug SH, Jonassen I, Øvreås L, Urich T (2012) CREST - Classification Resources for Environmental Sequence Tags, PLoS ONE 7:e49334
Licensed under: GNU GENERAL PUBLIC LICENSE, Version 3, 29 June 2007
Codes: https://github.com/lanzen/CREST/tree/master/LCAClassifier/src/LCAClassifier
"""
import logging
import re
import sys
from collections import defaultdict, OrderedDict
from Bio import Phylo
from hundo.blast import BlastHits
from hundo.fasta import read_fasta, format_fasta_record


BLAST6 = ["qseqid", "sseqid", "pident", "length", "mismatch", "gapopen", "qstart",
          "qend", "sstart", "send", "evalue", "bitscore"]


class Tree(object):
    ROOT = 0
    META = 1
    DOMAIN = 2
    SUPERKINGDOM = 3
    KINGDOM = 4
    PHYLUM = 5
    CLASS = 6
    ORDER = 7
    FAMILY = 8
    GENUS = 9
    SPECIES = 10
    SUBSPECIES = 11

    depths = {ROOT: 'root', META: 'meta', DOMAIN: 'domain', SUPERKINGDOM: 'superkingdom',
              KINGDOM: 'kingdom', PHYLUM: 'phylum', CLASS: 'class', ORDER: 'order',
              FAMILY: 'family', GENUS: 'genus', SPECIES: 'species', SUBSPECIES: 'strain'}

    def __init__(self, mapfile, trefile):

        self.tree = Phylo.read(trefile, "newick", values_are_confidence=True, rooted=True)
        self.root = self.tree.root
        self.names = {}
        self.node_names = {}
        self.node_ids = {}
        self.assignment_min = {}
        self.parents = {}
        self.no_hits = self.add_node("No hits", self.root)
        for child in self.get_all_children(self.root):
            self.node_ids[child.name] = child

        # why not just remove these from the map?
        accession_re = [re.compile("\D\D\d\d\d\d\d\d\Z"),
                       re.compile("\D\d\d\d\d\d\Z"),
                       re.compile("\D\D\D\D\d\d\d\d\d\d\d\d\d\Z"),
                       re.compile("\D\D\D\D\d\d\d\d\d\d\d\d\Z")]

        # Read nodes from .map file (id\t name\t cutoff)
        with open(mapfile) as fh:
            for line in fh:
                toks = line.strip().split("\t")
                node_id = toks[0]
                name = toks[1]
                similarity_cutoff = float(toks[3])

                # Find node and map name or accession to it
                n = self.node_ids.get(node_id)
                if n:
                    self.node_names[name] = n
                    # Unless this is just an accession, update node name and assignment min.
                    if similarity_cutoff >= 0 and \
                        not (accession_re[0].match(name) or \
                             accession_re[1].match(name) or \
                             accession_re[2].match(name) or \
                             accession_re[3].match(name)):
                        self.assignment_min[name] = similarity_cutoff
                        n.name = name
                else:
                    logging.error("Error: Node %s (%s) not found in tree" % (node_id, name))

    def verify_node(self, node):
        if isinstance(node, Phylo.BaseTree.Clade):
            return node
        elif isinstance(node, str):
            nn = node
            node = self.node_names.get(nn)
            if not node:
                logging.error("Verification Error: Node '%s' not found" % nn)
                return
            else:
                return node
        else:
            logging.error("Verification Error: Node %s is a strange instance" % node)
            return

    def add_node(self, nodename, parent, assignment_min=0):
        #insert instead of append?
        if nodename in self.node_names:
            logging.error("Node name '%s' is not unique - not added" % nodename)
            return None
        node = Phylo.Newick.Clade(name=nodename)
        parent = self.verify_node(parent)
        if not parent:
            return None
        parent.clades.append(node)
        self.node_names[nodename] = node
        self.assignment_min[node.name] = assignment_min
        self.parents[node] = parent
        return node

    def get_immediate_children(self, node):
        node = self.verify_node(node)
        children = []
        for c in node.clades:
            children.append(c)
        return children

    def get_parent(self, node):
        node = self.verify_node(node)
        if not node:
            return None
        if node in self.parents:
            return self.parents[node]
        else:
            p = self.tree.get_path(node)
            if p and len(p) > 1:
                parent = p[-2]
                self.parents[node] = parent
                return parent
            else:
                return self.tree.root

    def get_rank(self, node):
        depth = self.get_depth(node)
        if depth > Tree.SUBSPECIES:
            depth = Tree.SUBSPECIES
        return Tree.depths[depth]

    def get_depth(self, node):
        node = self.verify_node(node)
        pth = self.get_path(node)
        if len(pth)==1 and pth[0] is self.tree.root:
            return 0
        else:
            return len(pth)

    def get_path(self, node):
        plist = [node]
        if node is self.tree.root:
            return plist
        parent = self.get_parent(node)
        while parent and parent is not self.tree.root:
            plist = [parent] + plist
            parent = self.get_parent(parent)
        if not parent:
            logging.error("Cannot find parent beyond %s" % plist)
        else:
            return plist

    def get_common_ancestor(self, node_names):
        """Accepts a list of accessions (corresponding to tre file) incl. duplicates and returns LCA"""
        nodes = list(set([self.node_names.get(n) for n in node_names]))
        if len(nodes) == 1:
            return nodes[0]

        paths = sorted([self.get_path(n) for n in nodes], key=len)
        lca_path = paths[0]
        for path in paths[1:]:
            while not lca_path[-1] in path:
                if len(lca_path) == 1:
                    return self.tree.root
                else:
                    lca_path.pop()
        return lca_path[-1]

    def get_all_children(self, node, children=None, parent=None):
        if children is None:
            children = []
        for c in node.clades:
            self.get_all_children(c, children, parent=node)
        children.append(node)
        self.parents[node] = parent
        return children

    def get_taxonomy(self, node):
        taxonomy = OrderedDict()
        for i in "kpcofgs":
            taxonomy[i] = "?"
        if node is not None:
            for clade in self.get_path(node):
                depth = self.get_depth(clade)
                if depth > Tree.META and depth < Tree.SUBSPECIES and \
                    not depth == Tree.SUPERKINGDOM and not depth == Tree.KINGDOM:

                    if Tree.depths[depth][0] == "d":
                        abb = "k"
                    else:
                        abb = Tree.depths[depth][0]
                    taxonomy[abb] = clade.name.replace(" ","_")
        return taxonomy


class OTU(object):
    def __init__(self, name, sequence, classification=None):
        self.name = name
        self.sequence = sequence
        self.classification = classification


def parse_blasthits(blasthits, otus, tre, min_score=155, top_fraction=0.98, euk_filter=False):
    hsps = defaultdict(lambda: BlastHits(top_fraction=top_fraction))
    with open(blasthits) as blast_hits_fh:
        # TODO iterator as some may not be able to process very large files
        for hsp in blast_hits_fh:
            toks = dict(zip(BLAST6, hsp.strip().split("\t")))
            if float(toks["bitscore"]) < min_score: continue
            hsps[toks["qseqid"]].add(toks["sseqid"], float(toks["pident"]), toks["bitscore"])

    for otu_name, hits in hsps.items():
        otu = otus[otu_name]
        lca_node = tre.get_common_ancestor(hits.names)
        if not lca_node:
            logging.debug("No LCA -- assigning to No Hits: %s" % hits.names)
            otu.classification = tre.no_hits
            continue

        while lca_node.name in tre.assignment_min and \
                hits.percent_ids[-1] < tre.assignment_min[lca_node.name] and \
                lca_node is not tre.root:
            lca_node = tre.get_parent(lca_node)

        if euk_filter and tre.get_path(lca_node)[1].name == "Eukaryota":
            otu.classification = tre.no_hits
        else:
            otu.classification = lca_node
    return otus


def run_crest_classifier(fasta, blasthits, mapfile, trefile, outfasta, outtab, min_score, top_fraction, euk_filter):
    otus = OrderedDict()
    logging.info("Reading the input fasta (%s)" % fasta)
    with open(fasta) as fh:
        for name, seq in read_fasta(fh):
            otus[name] = OTU(name, seq)

    logging.info("Parsing the map and tree inputs")
    tre = Tree(mapfile, trefile)

    logging.info("Classifying BLAST hits")
    otus = parse_blasthits(blasthits, otus, tre, min_score, top_fraction, euk_filter)
    with open(outfasta, "w") as fasta_out, open(outtab, "w") as tsv_out:
        for otu_id, otu in otus.items():
            taxonomy = tre.get_taxonomy(otu.classification)
            full_name = "{name};tax={taxonomy}".format(name=otu.name, taxonomy=",".join(["%s__%s" % (abb, tax) for abb, tax in taxonomy.items()]))
            print(format_fasta_record(full_name, otu.sequence), file=fasta_out)
            print(otu_id, ";".join(["%s__%s" % (abb, tax) for abb, tax in taxonomy.items()]), sep="\t", file=tsv_out)
