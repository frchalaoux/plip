"""
Protein-Ligand Interaction Profiler - Analyze and visualize protein-ligand interactions in PDB files.
supplemental.py - Supplemental functions for PLIP analysis.
Copyright 2014-2015 Sebastian Salentin, Joachim Haupt

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

# Compatibility
from __future__ import print_function

# PLIP Modules
import config

# Python standard library
import re
from collections import namedtuple
import os
if os.name != 'nt':  # Resource module not available for Windows
    import resource
import subprocess
import codecs
import gzip
import zipfile

# External libraries
import pybel
from pybel import *
from openbabel import *
import numpy as np
from pymol import cmd
from pymol import finish_launching

# Settings
np.seterr(all='ignore')  # No runtime warnings


def tmpfile(prefix, direc):
    """Returns the path to a newly created temporary file."""
    return tempfile.mktemp(prefix=prefix, suffix='.pdb', dir=direc)


def is_lig(hetid):
    """Checks if a PDB compound can be excluded as a small molecule ligand"""
    h = hetid.upper()
    return not (h == 'HOH' or h in config.UNSUPPORTED)


def extract_pdbid(string):
    """Use regular expressions to get a PDB ID from a string"""
    p = re.compile("[0-9][0-9a-z]{3}")
    m = p.search(string.lower())
    try:
        return m.group()
    except AttributeError:
        return "UnknownProtein"


def whichrestype(atom):
    """Returns the residue name of an Pybel or OpenBabel atom."""
    atom = atom if not isinstance(atom, Atom) else atom.OBAtom  # Convert to OpenBabel Atom
    return atom.GetResidue().GetName() if atom.GetResidue() is not None else None


def whichresnumber(atom):
    """Returns the residue number of an Pybel or OpenBabel atom (numbering as in original PDB file)."""
    atom = atom if not isinstance(atom, Atom) else atom.OBAtom  # Convert to OpenBabel Atom
    return atom.GetResidue().GetNum() if atom.GetResidue() is not None else None


def whichchain(atom):
    """Returns the residue number of an PyBel or OpenBabel atom."""
    atom = atom if not isinstance(atom, Atom) else atom.OBAtom  # Convert to OpenBabel Atom
    return atom.GetResidue().GetChain() if atom.GetResidue() is not None else None

#########################
# Mathematical operations
#########################


def euclidean3d(v1, v2):
    """Faster implementation of euclidean distance for the 3D case."""
    if not len(v1) == 3 and len(v2) == 3:
        print("Vectors are not in 3D space. Returning None.")
        return None
    return np.sqrt((v1[0] - v2[0]) ** 2 + (v1[1] - v2[1]) ** 2 + (v1[2] - v2[2]) ** 2)


def vector(p1, p2):
    """Vector from p1 to p2.
    :param p1: coordinates of point p1
    :param p2: coordinates of point p2
    :returns : numpy array with vector coordinates
    """
    return None if len(p1) != len(p2) else np.array([p2[i] - p1[i] for i in xrange(len(p1))])


def vecangle(v1, v2, deg=True):
    """Calculate the angle between two vectors
    :param v1: coordinates of vector v1
    :param v2: coordinates of vector v2
    :returns : angle in degree or rad
    """
    if np.array_equal(v1, v2):
        return 0.0
    dm = np.dot(v1, v2)
    cm = np.linalg.norm(v1) * np.linalg.norm(v2)
    angle = np.arccos(round(dm / cm, 10))  # Round here to prevent floating point errors
    return np.degrees([angle, ])[0] if deg else angle


def normalize_vector(v):
    """Take a vector and return the normalized vector
    :param v: a vector v
    :returns : normalized vector v
    """
    norm = np.linalg.norm(v)
    return v/norm if not norm == 0 else v


def centroid(coo):
    """Calculates the centroid from a 3D point cloud and returns the coordinates
    :param coo: Array of coordinate arrays
    :returns : centroid coordinates as list
    """
    return map(np.mean, (([c[0] for c in coo]), ([c[1] for c in coo]), ([c[2] for c in coo])))


def projection(pnormal1, ppoint, tpoint):
    """Calculates the centroid from a 3D point cloud and returns the coordinates
    :param pnormal1: normal of plane
    :param ppoint: coordinates of point in the plane
    :param tpoint: coordinates of point to be projected
    :returns : coordinates of point orthogonally projected on the plane
    """
    # Choose the plane normal pointing to the point to be projected
    pnormal2 = [coo*(-1) for coo in pnormal1]
    d1 = euclidean3d(tpoint, pnormal1 + ppoint)
    d2 = euclidean3d(tpoint, pnormal2 + ppoint)
    pnormal = pnormal1 if d1 < d2 else pnormal2
    # Calculate the projection of tpoint to the plane
    sn = -np.dot(pnormal, vector(ppoint, tpoint))
    sd = np.dot(pnormal, pnormal)
    sb = sn / sd
    return [c1 + c2 for c1, c2 in zip(tpoint, [sb * pn for pn in pnormal])]


def cluster_doubles(double_list):
    """Given a list of doubles, they are clustered if they share one element
    :param double_list: list of doubles
    :returns : list of clusters (tuples)
    """
    location = {}  # hashtable of which cluster each element is in
    clusters = []
    # Go through each double
    for t in double_list:
        a, b = t[0], t[1]
        # If they both are already in different clusters, merge the clusters
        if a in location and b in location:
            if location[a] != location[b]:
                if location[a] < location[b]:
                    clusters[location[a]] = clusters[location[a]].union(clusters[location[b]])  # Merge clusters
                    clusters = clusters[:location[b]] + clusters[location[b]+1:]
                else:
                    clusters[location[b]] = clusters[location[b]].union(clusters[location[a]])  # Merge clusters
                    clusters = clusters[:location[a]] + clusters[location[a]+1:]
                # Rebuild index of locations for each element as they have changed now
                location = {}
                for i, cluster in enumerate(clusters):
                    for c in cluster:
                        location[c] = i
        else:
            # If a is already in a cluster, add b to that cluster
            if a in location:
                clusters[location[a]].add(b)
                location[b] = location[a]
            # If b is already in a cluster, add a to that cluster
            if b in location:
                clusters[location[b]].add(a)
                location[a] = location[b]
            # If neither a nor b is in any cluster, create a new one with a and b
            if not (b in location and a in location):
                clusters.append(set(t))
                location[a] = len(clusters) - 1
                location[b] = len(clusters) - 1
    return map(tuple, clusters)


#################
# File operations
#################

def tilde_expansion(folder_path):
    """Tilde expansion, i.e. converts '~' in paths into <value of $HOME>."""
    return os.path.expanduser(folder_path) if '~' in folder_path else folder_path


def folder_exists(folder_path):
    """Checks if a folder exists"""
    return os.path.exists(folder_path)


def create_folder_if_not_exists(folder_path):
    """Creates a folder if it does not exists."""
    folder_path = tilde_expansion(folder_path)
    folder_path = "".join([folder_path, '/']) if not folder_path[-1] == '/' else folder_path
    direc = os.path.dirname(folder_path)
    if not folder_exists(direc):
        os.makedirs(direc)


def cmd_exists(c):
    return subprocess.call("type " + c, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) == 0

################
# PyMOL-specific
################


def object_exists(object_name):
    """Checks if an object exists in the open PyMOL session."""
    return object_name in cmd.get_names("objects")


def initialize_pymol(options):
    """Initializes PyMOL"""
    # Pass standard arguments of function to prevent PyMOL from printing out PDB headers (workaround)
    finish_launching(args=['pymol', options, '-K'])
    cmd.reinitialize()


def start_pymol(quiet=False, options='-p', run=False):
    """Starts up PyMOL and sets general options. Quiet mode suppresses all PyMOL output.
    Command line options can be passed as the second argument."""
    import pymol
    pymol.pymol_argv = ['pymol', '%s' % options] + sys.argv[1:]
    if run:
        initialize_pymol(options)
    if quiet:
        cmd.feedback('disable', 'all', 'everything')


def standard_settings():
    """Sets up standard settings for a nice visualization."""
    cmd.set('bg_rgb', [1.0, 1.0, 1.0])  # White background
    cmd.set('depth_cue', 0)  # Turn off depth cueing (no fog)
    cmd.set('cartoon_side_chain_helper', 1)  # Improve combined visualization of sticks and cartoon
    cmd.set('cartoon_fancy_helices', 1)  # Nicer visualization of helices (using tapered ends)
    cmd.set('transparency_mode', 1)  # Turn on multilayer transparency
    cmd.set('dash_radius', 0.05)
    set_custom_colorset()


def set_custom_colorset():
    """Defines a colorset with matching colors. Provided by Joachim."""
    cmd.set_color('myorange', '[253, 174, 97]')
    cmd.set_color('mygreen', '[171, 221, 164]')
    cmd.set_color('myred', '[215, 25, 28]')
    cmd.set_color('myblue', '[43, 131, 186]')
    cmd.set_color('mylightblue', '[158, 202, 225]')
    cmd.set_color('mylightgreen', '[229, 245, 224]')


def nucleotide_linkage(residues):
    """Support for DNA/RNA ligands by finding missing covalent linkages to stitch DNA/RNA together."""

    nuc_covalent = []
    #######################################
    # Basic support for RNA/DNA as ligand #
    #######################################
    nucleotides = ['A', 'C', 'T', 'G', 'U', 'DA', 'DC', 'DT', 'DG', 'DU']
    dna_rna = {}  # Dictionary of DNA/RNA residues by chain
    covlinkage = namedtuple("covlinkage", "id1 chain1 pos1 conf1 id2 chain2 pos2 conf2")
    # Create missing covlinkage entries for DNA/RNA
    for ligand in residues:
        resname, chain, pos = ligand
        if resname in nucleotides:
            if chain not in dna_rna:
                dna_rna[chain] = [(resname, pos), ]
            else:
                dna_rna[chain].append((resname, pos))
    for chain in dna_rna:
        nuc_list = dna_rna[chain]
        for i, nucleotide in enumerate(nuc_list):
            if not i == len(nuc_list) - 1:
                name, pos = nucleotide
                nextnucleotide = nuc_list[i + 1]
                nextname, nextpos = nextnucleotide
                newlink = covlinkage(id1=name, chain1=chain, pos1=pos, conf1='',
                                     id2=nextname, chain2=chain, pos2=nextpos, conf2='')
                nuc_covalent.append(newlink)

    return nuc_covalent


def classify_by_name(names):
    """Classify a (composite) ligand by the HETID(s)"""
    if len(names) > 3:  # Polymer
        if len({'U', 'A', 'C', 'G'}.intersection(set(names))) != 0:
            ligtype = 'RNA'
        elif len({'DT', 'DA', 'DC', 'DG'}.intersection(set(names))) != 0:
            ligtype = 'DNA'
        else:
            ligtype = "POLYMER"
    else:
        ligtype = 'SMALLMOLECULE'

    for name in names:
        if name in config.METAL_IONS:
            if len(names) == 1:
                ligtype = 'ION'
            else:
                if "ION" not in ligtype:
                    ligtype += '+ION'
    return ligtype


def get_isomorphisms(reference, lig):
    """Get all isomorphisms of the ligand."""
    query = pybel.ob.CompileMoleculeQuery(reference.OBMol)
    mappr = pybel.ob.OBIsomorphismMapper.GetInstance(query)
    if all:
        isomorphs = pybel.ob.vvpairUIntUInt()
        mappr.MapAll(lig.OBMol, isomorphs)
    else:
        isomorphs = pybel.ob.vpairUIntUInt()
        mappr.MapFirst(lig.OBMol, isomorphs)
        isomorphs = [isomorphs]
    debuglog("Number of isomorphisms: %i" % len(isomorphs))
    # #@todo Check which isomorphism to take
    return isomorphs


def canonicalize(lig):
    """Get the canonical atom order for the ligand."""
    atomorder = None
    # Get canonical atom order

    lig = pybel.ob.OBMol(lig.OBMol)
    for bond in pybel.ob.OBMolBondIter(lig):
        if bond.GetBondOrder() != 1:
            bond.SetBondOrder(1)
    lig.DeleteData(pybel.ob.StereoData)
    lig = pybel.Molecule(lig)
    testcan = lig.write(format='can')
    try:
        pybel.readstring('can', testcan)
        reference = pybel.readstring('can', testcan)
    except IOError:
        testcan, reference = '', ''
    if testcan != '':
        reference.removeh()
        isomorphs = get_isomorphisms(reference, lig)  # isomorphs now holds all isomorphisms within the molecule
        if not len(isomorphs) == 0:
            smi_dict = {}
            smi_to_can = isomorphs[0]
            for x in smi_to_can:
                smi_dict[int(x[1]) + 1] = int(x[0]) + 1
            atomorder = [smi_dict[x + 1] for x in range(len(lig.atoms))]
        else:
            atomorder = None
    return atomorder


def int32_to_negative(int32):
    """Checks if a suspicious number (e.g. ligand position) is in fact a negative number represented as a
    32 bit integer and returns the actual number.
    """
    dct = {}
    if int32 == 4294967295:  # Special case in some structures (note, this is just a workaround)
        return -1
    for i in range(-1000, -1):
        dct[np.uint32(i)] = i
    if int32 in dct:
        return dct[int32]
    else:
        return int32


def read_pdb(pdbfname):
    """Reads a given PDB file and returns a Pybel Molecule."""
    pybel.ob.obErrorLog.StopLogging()  # Suppress all OpenBabel warnings
    if os.name != 'nt':  # Resource module not available for Windows
        maxsize = resource.getrlimit(resource.RLIMIT_STACK)[-1]
        resource.setrlimit(resource.RLIMIT_STACK, (min(2 ** 28, maxsize), maxsize))
    sys.setrecursionlimit(10 ** 5)  # increase Python recoursion limit
    return readmol(pdbfname)


def read(fil):
    """Returns a file handler and detects gzipped files."""
    if os.path.splitext(fil)[-1] == '.gz':
        return gzip.open(fil, 'rb')
    elif os.path.splitext(fil)[-1] == '.zip':
        zf = zipfile.ZipFile(fil, 'r')
        return zf.open(zf.infolist()[0].filename)
    else:
        try:
            codecs.open(fil, 'r', 'utf-8').read()
            return codecs.open(fil, 'r', 'utf-8')
        except UnicodeDecodeError:
            return open(fil, 'r')


def readmol(path):
    """Reads the given molecule file and returns the corresponding Pybel molecule as well as the input file type.
    In contrast to the standard Pybel implementation, the file is closed properly."""
    supported_formats = ['pdb', 'pdbqt', 'mmcif']
    obc = pybel.ob.OBConversion()

    with read(path) as f:
        filestr = str(f.read())

    for sformat in supported_formats:
        obc.SetInFormat(sformat)
        mol = pybel.ob.OBMol()
        obc.ReadString(mol, filestr)
        if not mol.Empty():
            if sformat == 'pdbqt':
                message('[EXPERIMENTAL] Input is PDBQT file. Some features (especially visualization) might not '
                        'work as expected. Please consider using PDB format instead.\n')
            if sformat == 'mmcif':
                message('[EXPERIMENTAL] Input is mmCIF file. Most features do currently not work with this format.\n')
            return pybel.Molecule(mol), sformat
    sysexit(4, 'No valid file format provided.')


def sysexit(code, msg):
    """Exit using an custom error message and error code."""
    sys.stderr.write(msg)
    sys.exit(code)


def message(msg, indent=False):
    """Writes messages in verbose mode"""
    if config.VERBOSE:
        if indent:
            msg = '  ' + msg
        sys.stdout.write(msg)


def debuglog(msg):
    """Writes debug messages"""
    if config.DEBUG:
        msg = '    %% DEBUG: ' + msg
        if len(msg) > 100:
            msg = msg[:100] + ' ...'
        msg += '\n'
        sys.stdout.write(msg)
