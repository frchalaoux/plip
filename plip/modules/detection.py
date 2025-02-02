"""
Protein-Ligand Interaction Profiler - Analyze and visualize protein-ligand interactions in PDB files.
detection.py - Detect non-covalent interactions.
Copyright 2014-2015 Sebastian Salentin

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

# Python standard library
import itertools
from collections import defaultdict

# Own modules
from supplemental import *
import config


##################################################
# FUNCTIONS FOR DETECTION OF SPECIFIC INTERACTIONS
##################################################

def hydrophobic_interactions(atom_set_a, atom_set_b):
    """Detection of hydrophobic pliprofiler between atom_set_a (binding site) and atom_set_b (ligand).
    Definition: All pairs of qualified carbon atoms within a distance of HYDROPH_DIST_MAX
    """
    data = namedtuple('hydroph_interaction', 'bsatom bsatom_orig_idx ligatom ligatom_orig_idx '
                                             'distance restype resnr reschain')
    pairings = []
    for a, b in itertools.product(atom_set_a, atom_set_b):
        e = euclidean3d(a.atom.coords, b.atom.coords)
        if e < config.HYDROPH_DIST_MAX:
            contact = data(bsatom=a.atom, bsatom_orig_idx=a.orig_idx, ligatom=b.atom, ligatom_orig_idx=b.orig_idx,
                           distance=e, restype=whichrestype(a.atom), resnr=whichresnumber(a.atom),
                           reschain=whichchain(a.atom))
            pairings.append(contact)
    return pairings


def hbonds(acceptors, donor_pairs, protisdon, typ):
    """Detection of hydrogen bonds between sets of acceptors and donor pairs.
    Definition: All pairs of hydrogen bond acceptor and donors with
    donor hydrogens and acceptor showing a distance within HBOND DIST MIN and HBOND DIST MAX
    and donor angles above HBOND_DON_ANGLE_MIN
    """
    data = namedtuple('hbond', 'a a_orig_idx d d_orig_idx h distance_ah distance_ad angle type protisdon resnr '
                               'restype reschain sidechain atype dtype')
    pairings = []
    for acc, don in itertools.product(acceptors, donor_pairs):
        if typ == 'strong':  # Regular (strong) hydrogen bonds
            dist_ah = euclidean3d(acc.a.coords, don.h.coords)
            dist_ad = euclidean3d(acc.a.coords, don.d.coords)
            if dist_ad < config.HBOND_DIST_MAX:
                vec1, vec2 = vector(don.h.coords, don.d.coords), vector(don.h.coords, acc.a.coords)
                v = vecangle(vec1, vec2)
                if v > config.HBOND_DON_ANGLE_MIN:
                    restype = whichrestype(don.d) if protisdon else whichrestype(acc.a)
                    reschain = whichchain(don.d) if protisdon else whichchain(acc.a)
                    protatom = don.d.OBAtom if protisdon else acc.a.OBAtom
                    is_sidechain_hbond = protatom.GetResidue().GetAtomProperty(protatom, 8)  # Check if sidechain atom
                    resnr = whichresnumber(don.d)if protisdon else whichresnumber(acc.a)
                    contact = data(a=acc.a, a_orig_idx=acc.a_orig_idx, d=don.d, d_orig_idx=don.d_orig_idx, h=don.h,
                                   distance_ah=dist_ah, distance_ad=dist_ad, angle=v, type=typ, protisdon=protisdon,
                                   resnr=resnr, restype=restype, reschain=reschain, sidechain=is_sidechain_hbond,
                                   atype=acc.a.type, dtype=don.d.type)
                    pairings.append(contact)
    return pairings


def pistacking(rings_bs, rings_lig):
    """Return all pi-stackings between the given aromatic ring systems in receptor and ligand."""
    data = namedtuple('pistack', 'proteinring ligandring distance angle offset type restype resnr reschain')
    pairings = []
    for r, l in itertools.product(rings_bs, rings_lig):
        # DISTANCE AND RING ANGLE CALCULATION
        d = euclidean3d(r.center, l.center)
        b = vecangle(r.normal, l.normal)
        a = min(b, 180 - b if not 180 - b < 0 else b)  # Smallest of two angles, depending on direction of normal

        # RING CENTER OFFSET CALCULATION (project each ring center into the other ring)
        proj1 = projection(l.normal, l.center, r.center)
        proj2 = projection(r.normal, r.center, l.center)
        offset = min(euclidean3d(proj1, l.center), euclidean3d(proj2, r.center))

        # RECEPTOR DATA
        resnr, restype, reschain = whichresnumber(r.atoms[0]), whichrestype(r.atoms[0]), whichchain(r.atoms[0])

        # SELECTION BY DISTANCE, ANGLE AND OFFSET
        if d < config.PISTACK_DIST_MAX:
            if 0 < a < config.PISTACK_ANG_DEV and offset < config.PISTACK_OFFSET_MAX:
                contact = data(proteinring=r, ligandring=l, distance=d, angle=a, offset=offset,
                               type='P', resnr=resnr, restype=restype, reschain=reschain)
                pairings.append(contact)
            if 90 - config.PISTACK_ANG_DEV < a < 90 + config.PISTACK_ANG_DEV and offset < config.PISTACK_OFFSET_MAX:
                contact = data(proteinring=r, ligandring=l, distance=d, angle=a, offset=offset,
                               type='T', resnr=resnr, restype=restype, reschain=reschain)
                pairings.append(contact)
    return pairings


def pication(rings, pos_charged, protcharged):
    """Return all pi-Cation interaction between aromatic rings and positively charged groups.
    For tertiary and quaternary amines, check also the angle between the ring and the nitrogen.
    """
    data = namedtuple('pication', 'ring charge distance offset type restype resnr reschain protcharged')
    pairings = []
    if not len(rings) == 0 and not len(pos_charged) == 0:
        for ring in rings:
            c = ring.center
            for p in pos_charged:
                d = euclidean3d(c, p.center)
                # Project the center of charge into the ring and measure distance to ring center
                proj = projection(ring.normal, ring.center, p.center)
                offset = euclidean3d(proj, ring.center)
                if d < config.PICATION_DIST_MAX and offset < config.PISTACK_OFFSET_MAX:
                    if type(p).__name__ == 'lcharge' and p.fgroup == 'tertamine':
                        # Special case here if the ligand has a tertiary amine, check an additional angle
                        # Otherwise, we might have have a pi-cation interaction 'through' the ligand
                        n_atoms = [a_neighbor for a_neighbor in OBAtomAtomIter(p.atoms[0].OBAtom)]
                        n_atoms_coords = [(a.x(), a.y(), a.z()) for a in n_atoms]
                        amine_normal = np.cross(vector(n_atoms_coords[0], n_atoms_coords[1]),
                                                vector(n_atoms_coords[2], n_atoms_coords[0]))
                        b = vecangle(ring.normal, amine_normal)
                        # Smallest of two angles, depending on direction of normal
                        a = min(b, 180 - b if not 180 - b < 0 else b)
                        if not a > 30.0:
                            resnr, restype = whichresnumber(ring.atoms[0]), whichrestype(ring.atoms[0])
                            reschain = whichchain(ring.atoms[0])
                            contact = data(ring=ring, charge=p, distance=d, offset=offset, type='regular',
                                           restype=restype, resnr=resnr, reschain=reschain, protcharged=protcharged)
                            pairings.append(contact)
                        break
                    resnr = whichresnumber(p.atoms[0]) if protcharged else whichresnumber(ring.atoms[0])
                    restype = whichrestype(p.atoms[0]) if protcharged else whichrestype(ring.atoms[0])
                    reschain = whichchain(p.atoms[0]) if protcharged else whichchain(ring.atoms[0])
                    contact = data(ring=ring, charge=p, distance=d, offset=offset, type='regular', restype=restype,
                                   resnr=resnr, reschain=reschain, protcharged=protcharged)
                    pairings.append(contact)
    return pairings


def saltbridge(poscenter, negcenter, protispos):
    """Detect all salt bridges (pliprofiler between centers of positive and negative charge)"""
    data = namedtuple('saltbridge', 'positive negative distance protispos resnr restype reschain')
    pairings = []
    for pc, nc in itertools.product(poscenter, negcenter):
        if euclidean3d(pc.center, nc.center) < config.SALTBRIDGE_DIST_MAX:
            resnr = pc.resnr if protispos else nc.resnr
            restype = pc.restype if protispos else nc.restype
            reschain = pc.reschain if protispos else nc.reschain
            contact = data(positive=pc, negative=nc, distance=euclidean3d(pc.center, nc.center), protispos=protispos,
                           resnr=resnr, restype=restype, reschain=reschain)
            pairings.append(contact)
    return pairings


def halogen(acceptor, donor):
    """Detect all halogen bonds of the type Y-O...X-C"""
    data = namedtuple('halogenbond', 'acc acc_orig_idx don don_orig_idx distance don_angle acc_angle restype '
                                     'resnr reschain donortype acctype sidechain')
    pairings = []
    for acc, don in itertools.product(acceptor, donor):
        dist = euclidean3d(acc.o.coords, don.x.coords)
        if dist < config.HALOGEN_DIST_MAX:
            vec1, vec2 = vector(acc.o.coords, acc.y.coords), vector(acc.o.coords, don.x.coords)
            vec3, vec4 = vector(don.x.coords, acc.o.coords), vector(don.x.coords, don.c.coords)
            acc_angle, don_angle = vecangle(vec1, vec2), vecangle(vec3, vec4)
            is_sidechain_hal = acc.o.OBAtom.GetResidue().GetAtomProperty(acc.o.OBAtom, 8)  # Check if sidechain atom
            if config.HALOGEN_ACC_ANGLE - config.HALOGEN_ANGLE_DEV < acc_angle \
                    < config.HALOGEN_ACC_ANGLE + config.HALOGEN_ANGLE_DEV:
                if config.HALOGEN_DON_ANGLE - config.HALOGEN_ANGLE_DEV < don_angle \
                        < config.HALOGEN_DON_ANGLE + config.HALOGEN_ANGLE_DEV:
                    contact = data(acc=acc, acc_orig_idx=acc.o_orig_idx, don=don, don_orig_idx=don.x_orig_idx,
                                   distance=dist, don_angle=don_angle, acc_angle=acc_angle,
                                   restype=whichrestype(acc.o), resnr=whichresnumber(acc.o),
                                   reschain=whichchain(acc.o), donortype=don.x.OBAtom.GetType(), acctype=acc.o.type,
                                   sidechain=is_sidechain_hal)
                    pairings.append(contact)
    return pairings


def water_bridges(bs_hba, lig_hba, bs_hbd, lig_hbd, water):
    """Find water-bridged hydrogen bonds between ligand and protein. For now only considers bridged of first degree."""
    data = namedtuple('waterbridge', 'a a_orig_idx atype d d_orig_idx dtype h water water_orig_idx distance_aw '
                                     'distance_dw d_angle w_angle type resnr restype reschain protisdon')
    pairings = []
    # First find all acceptor-water pairs with distance within d
    # and all donor-water pairs with distance within d and angle greater theta
    lig_aw, prot_aw, lig_dw, prot_hw = [], [], [], []
    for w in water:
        for acc1 in lig_hba:
            dist = euclidean3d(acc1.a.coords, w.oxy.coords)
            if config.WATER_BRIDGE_MINDIST <= dist <= config.WATER_BRIDGE_MAXDIST:
                lig_aw.append((acc1, w, dist))
        for acc2 in bs_hba:
            dist = euclidean3d(acc2.a.coords, w.oxy.coords)
            if config.WATER_BRIDGE_MINDIST <= dist <= config.WATER_BRIDGE_MAXDIST:
                prot_aw.append((acc2, w, dist))
        for don1 in lig_hbd:
            dist = euclidean3d(don1.d.coords, w.oxy.coords)
            d_angle = vecangle(vector(don1.h.coords, don1.d.coords), vector(don1.h.coords, w.oxy.coords))
            if config.WATER_BRIDGE_MINDIST <= dist <= config.WATER_BRIDGE_MAXDIST \
                    and d_angle > config.WATER_BRIDGE_THETA_MIN:
                lig_dw.append((don1, w, dist, d_angle))
        for don2 in bs_hbd:
            dist = euclidean3d(don2.d.coords, w.oxy.coords)
            d_angle = vecangle(vector(don2.h.coords, don2.d.coords), vector(don2.h.coords, w.oxy.coords))
            if config.WATER_BRIDGE_MINDIST <= dist <= config.WATER_BRIDGE_MAXDIST \
                    and d_angle > config.WATER_BRIDGE_THETA_MIN:
                prot_hw.append((don2, w, dist, d_angle))

    for l, p in itertools.product(lig_aw, prot_hw):
        acc, wl, distance_aw = l
        don, wd, distance_dw, d_angle = p
        if wl.oxy == wd.oxy:  # Same water molecule and angle within omega
            w_angle = vecangle(vector(acc.a.coords, wl.oxy.coords), vector(wl.oxy.coords, don.h.coords))
            if config.WATER_BRIDGE_OMEGA_MIN < w_angle < config.WATER_BRIDGE_OMEGA_MAX:
                contact = data(a=acc.a, a_orig_idx=acc.a_orig_idx, atype=acc.a.type, d=don.d, d_orig_idx=don.d_orig_idx,
                               dtype=don.d.type, h=don.h, water=wl.oxy, water_orig_idx=wl.oxy_orig_idx,
                               distance_aw=distance_aw, distance_dw=distance_dw, d_angle=d_angle, w_angle=w_angle,
                               type='first_deg', resnr=whichresnumber(don.d), restype=whichrestype(don.d),
                               reschain=whichchain(don.d), protisdon=True)
                pairings.append(contact)
    for p, l in itertools.product(prot_aw, lig_dw):
        acc, wl, distance_aw = p
        don, wd, distance_dw, d_angle = l
        if wl.oxy == wd.oxy:  # Same water molecule and angle within omega
            w_angle = vecangle(vector(acc.a.coords, wl.oxy.coords), vector(wl.oxy.coords, don.h.coords))
            if config.WATER_BRIDGE_OMEGA_MIN < w_angle < config.WATER_BRIDGE_OMEGA_MAX:
                contact = data(a=acc.a, a_orig_idx=acc.a_orig_idx, atype=acc.a.type, d=don.d, d_orig_idx=don.d_orig_idx,
                               dtype=don.d.type, h=don.h, water=wl.oxy, water_orig_idx=wl.oxy_orig_idx,
                               distance_aw=distance_aw, distance_dw=distance_dw,
                               d_angle=d_angle, w_angle=w_angle, type='first_deg', resnr=whichresnumber(acc.a),
                               restype=whichrestype(acc.a), reschain=whichchain(acc.a), protisdon=False)
                pairings.append(contact)
    return pairings


def metal_complexation(metals, metal_binding_lig, metal_binding_bs):
    """Find all metal complexes between metals and appropriate groups in both protein and ligand, as well as water"""
    data = namedtuple('metal_complex', 'metal metal_orig_idx metal_type target target_orig_idx target_type '
                                       'coordination_num distance resnr restype '
                                       'reschain location rms, geometry num_partners complexnum')
    pairings_dict = {}
    pairings = []
    # #@todo Refactor
    metal_to_id = {}
    for metal, target in itertools.product(metals, metal_binding_lig + metal_binding_bs):
        distance = euclidean3d(metal.m.coords, target.atom.coords)
        if distance < config.METAL_DIST_MAX:
            if metal.m not in pairings_dict:
                pairings_dict[metal.m] = [(target, distance), ]
                metal_to_id[metal.m] = metal.m_orig_idx
            else:
                pairings_dict[metal.m].append((target, distance))
    for cnum, metal in enumerate(pairings_dict):
        rms = 0.0
        excluded = []
        # cnum +1 being the complex number
        contact_pairs = pairings_dict[metal]
        num_targets = len(contact_pairs)
        vectors_dict = defaultdict(list)
        for contact_pair in contact_pairs:
            target, distance = contact_pair
            vectors_dict[target.atom.idx].append(vector(metal.coords, target.atom.coords))

        # Listing of coordination numbers and their geometries
        configs = {2: ['linear', ],
                   3: ['trigonal.planar', 'trigonal.pyramidal'],
                   4: ['tetrahedral', 'square.planar'],
                   5: ['trigonal.bipyramidal', 'square.pyramidal'],
                   6: ['octahedral', ]}

        # Angle signatures for each geometry (as seen from each target atom)
        ideal_angles = {'linear': [[180.0]] * 2,
                        'trigonal.planar': [[120.0, 120.0]] * 3,
                        'trigonal.pyramidal': [[109.5, 109.5]] * 3,
                        'tetrahedral': [[109.5, 109.5, 109.5, 109.5]] * 4,
                        'square.planar': [[90.0, 90.0, 90.0, 90.0]] * 4,
                        'trigonal.bipyramidal': [[120.0, 120.0, 90.0, 90.0]] * 3 + [[90.0, 90.0, 90.0, 180.0]] * 2,
                        'square.pyramidal': [[90.0, 90.0, 90.0, 180.0]] * 4 + [[90.0, 90.0, 90.0, 90.0]],
                        'octahedral': [[90.0, 90.0, 90.0, 90.0, 180.0]] * 6}
        angles_dict = {}

        for target in vectors_dict:
            cur_vector = vectors_dict[target]
            other_vectors = []
            for t in vectors_dict:
                if not t == target:
                    [other_vectors.append(x) for x in vectors_dict[t]]
            angles = [vecangle(pair[0], pair[1]) for pair in itertools.product(cur_vector, other_vectors)]
            angles_dict[target] = angles

        all_total = []  # Record fit information for each geometry tested
        gdata = namedtuple('gdata', 'geometry rms coordination excluded diff_targets')  # Geometry Data
        # Can't specify geometry with only one target
        if num_targets == 1:
            final_geom = 'NA'
            final_coo = 1
            excluded = []
            rms = 0.0
        else:
            for coo in sorted(configs, reverse=True):  # Start with highest coordination number
                geometries = configs[coo]
                for geometry in geometries:
                    signature = ideal_angles[geometry]  # Set of ideal angles for geometry, from each perspective
                    geometry_total = 0
                    geometry_scores = []  # All scores for one geometry (from all subsignatures)
                    used_up_targets = []  # Use each target just once for a subsignature
                    not_used = []
                    coo_diff = num_targets - coo  # How many more observed targets are there?

                    # Find best match for each subsignature
                    for subsignature in signature:  # Ideal angles from one perspective
                        best_target = None  # There's one best-matching target for each subsignature
                        best_target_score = 999

                        for k, target in enumerate(angles_dict):
                            if target not in used_up_targets:
                                observed_angles = angles_dict[target]  # Observed angles from perspective of one target
                                single_target_scores = []
                                used_up_observed_angles = []
                                for i, ideal_angle in enumerate(subsignature):
                                    # For each angle in the signature, find the best-matching observed angle
                                    best_match = None
                                    best_match_diff = 999
                                    for j, observed_angle in enumerate(observed_angles):
                                        if j not in used_up_observed_angles:
                                            diff = abs(ideal_angle - observed_angle)
                                            if diff < best_match_diff:
                                                best_match_diff = diff
                                                best_match = j
                                    if best_match is not None:
                                        used_up_observed_angles.append(best_match)
                                        single_target_scores.append(best_match_diff)
                                # Calculate RMS for target angles
                                target_total = sum([x ** 2 for x in single_target_scores]) ** 0.5  # Tot. score targ/sig
                                if target_total < best_target_score:
                                    best_target_score = target_total
                                    best_target = target

                        used_up_targets.append(best_target)
                        geometry_scores.append(best_target_score)
                        # Total score is mean of RMS values
                        geometry_total = np.mean(geometry_scores)
                    # Record the targets not used for excluding them when deciding for a final geometry
                    [not_used.append(target) for target in angles_dict if target not in used_up_targets]
                    all_total.append(gdata(geometry=geometry, rms=geometry_total, coordination=coo,
                                           excluded=not_used, diff_targets=coo_diff))

        # Make a decision here. Starting with the geometry with lowest difference in ideal and observed partners ...
        # Check if the difference between the RMS to the next best solution is not larger than 0.5
        if not num_targets == 1:  # Can't decide for any geoemtry in that case
            all_total = sorted(all_total, key=lambda x: abs(x.diff_targets))
            for i, total in enumerate(all_total):
                next_total = all_total[i + 1]
                this_rms, next_rms = total.rms, next_total.rms
                diff_to_next = next_rms - this_rms
                if diff_to_next > 0.5:
                    final_geom, final_coo, rms, excluded = total.geometry, total.coordination, total.rms, total.excluded
                    break
                elif next_total.rms < 3.5:
                    final_geom, final_coo, = next_total.geometry, next_total.coordination
                    rms, excluded = next_total.rms, next_total.excluded
                    break
                elif i == len(all_total) - 1:
                    final_geom, final_coo, rms, excluded = "NA", "NA", 0.0, []

        # Record all contact pairing, excluding those with targets superfluous for chosen geometry
        only_water = set([x[0].location for x in contact_pairs]) == {'water'}
        if not only_water:  # No complex if just with water as targets
            message("Metal ion %s complexed with %s geometry (coo. number %r/ %i observed).\n"
                    % (metal.type, final_geom, final_coo, num_targets), indent=True)
            for contact_pair in contact_pairs:
                target, distance = contact_pair
                if target.atom.idx not in excluded:
                    contact = data(metal=metal, metal_orig_idx=metal_to_id[metal], metal_type=metal.type,
                                   target=target, target_orig_idx=target.atom_orig_idx, target_type=target.type,
                                   coordination_num=final_coo, distance=distance, resnr=target.resnr,
                                   restype=target.restype, reschain=target.reschain, location=target.location,
                                   rms=rms, geometry=final_geom, num_partners=num_targets, complexnum=cnum + 1)
                    pairings.append(contact)
    return pairings
