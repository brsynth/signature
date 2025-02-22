"""This library compute signature on atoms and molecules using RDKit.

Molecule signature: the signature of a molecule is composed of the signature of
its atoms. Molecule signatures are implemented using MoleculeSignature objects.

Atom signature are represented by a rooted SMILES string (the root is the atom
laleled 1). Atom signatures are implemented as AtomSignature objects.

Below are format examples for the oxygen atom in phenol with radius=2
  - Default (nbits=0)
    C:C(:C)[OH:1]
    here the root is the oxygen atom labeled 1: [OH:1]
  - nbits=2048
    91,C:C(:C)[OH:1]
    91 is the Morgan bit of oxygen computed at radius 2

Atom signature can also be computed using neighborhood. A signature neighbor
(string) is the signature of the atom at radius followed but its signature at
raduis-1 and the atom signatutre of its neighbor computed at radius-1

Example:
signature = C:C(:C)[OH:1]
signature-neighbor = C:C(:C)[OH:1]&C[OH:1].SINGLE|C:[C:1](:C)O
    after token &,  the signature is computed for the root (Oxygen)
    and its neighbor for radius-1, root and neighbor are separated by '.'
    The oxygen atom is linked by a SINGLE bond to a carbon of signature C:[C:1](:C)O

Authors:
  - Jean-loup Faulon <jfaulon@gmail.com>
  - Thomas Duigou <thomas.duigou@inrae.fr>
  - Philippe Meyer <philippe.meyer@inrae.fr>
"""

import logging
import re
from typing import List, Tuple

from rdkit import Chem
from rdkit.Chem import rdFingerprintGenerator

# Logging settings
logger = logging.getLogger(__name__)

# =================================================================================================
# Atom Signature
# =================================================================================================


class AtomSignature:
    """Class representing the signature of an atom."""

    # Separators defined at the class level
    _BIT_SEP = "-"
    _MORGAN_SEP = " ## "
    _NEIG_SEP = " && "
    _BOND_SEP = " <> "

    def __init__(
        self,
        atom: Chem.Atom = None,
        radius: int = 2,
        morgan_bits: None | list[int] = None,
        boundary_bonds: bool = False,
        map_root: bool = True,
        rooted: bool = False,
        **kwargs: dict,
    ) -> None:
        """Initialize the AtomSignature object

        Parameters
        ----------
        atom : Chem.Atom
            The atom to generate the signature for.
        radius : int
            The radius of the environment to consider.
        boundary_bonds : bool
            Whether to add bonds at the boundary of the radius.
        map_root : bool
            Whether to map the root atom in the signature. If yes, the root atom
            is labeled as 1.
        rooted : bool
            Whether to use rooted SMARTS/SMILES syntax for the signature. If
            yes, the signature is rooted at the root atom.
        morgan_bits : None | list[int]
            The Morgan bit(s) of the atom.
        **kwargs
            Additional arguments to pass to Chem.MolFragmentToSmiles calls.
        """
        # Parameters reminder
        self.kwargs = clean_kwargs(kwargs)

        # Meaningful information
        self._morgans = morgan_bits
        self._root = None
        self._root_minus = None
        self._neighbors = []

        # Early return if the atom is None
        if atom is None:
            return
        else:
            assert isinstance(atom, Chem.Atom), "atom must be a RDKit atom object"

        # Refine the Morgan bit
        if isinstance(self._morgans, list):
            self._morgans = tuple(self._morgans)

        # Compute signature of the atom itself
        self._root = self.atom_signature(
            atom,
            radius,
            boundary_bonds,
            map_root,
            rooted,
            **self.kwargs,
        )

    def __repr__(self) -> str:
        _ = "AtomSignature("
        _ += f"morgans={self._morgans}, "
        _ += f"root='{self._root}', "
        _ += f"root_minus='{self._root_minus}', "
        _ += f"neighbors={self._neighbors}"
        _ += ")"
        return _

    def __lt__(self, other) -> bool:
        if self.morgans == other.morgans:
            if self.root == other.root:
                if self.neighbors == other.neighbors:
                    return False
                return self.neighbors < other.neighbors
            return self.root < other.root
        return self.morgans < other.morgans

    def __eq__(self, other) -> bool:
        # check if the signature are the same type
        if not isinstance(other, AtomSignature):
            return False
        return (
            self.morgans == other.morgans
            and self.root == other.root
            and self.neighbors == other.neighbors
        )

    @property
    def morgans(self) -> None | list[int]:
        return self._morgans

    @property
    def root(self) -> str:
        return self._root

    @property
    def root_minus(self) -> str:
        return self._root_minus

    @property
    def neighbors(self) -> tuple:
        return self._neighbors

    def to_string(self, neighbors=False, morgans=True) -> str:
        """Return the signature as a string

        Returns
        -------
        str
            The signature as a string
        """
        if self.morgans is None or not morgans:
            _ = ""
        elif isinstance(self._morgans, (list, tuple)):
            _ = f"{self._BIT_SEP.join([str(bit) for bit in self._morgans])}{self._MORGAN_SEP}"
        else:
            raise NotImplementedError("Morgan bits must be 'None' or a list of integers")
        if neighbors:
            _ += f"{self._root_minus}{self._NEIG_SEP}"
            _ += self._NEIG_SEP.join(
                [f"{bond}{self._BOND_SEP}{sig}" for bond, sig in self.neighbors]
            )
        else:
            _ += self._root
        return _

    @classmethod
    def from_string(cls, signature: str) -> None:
        """Initialize the AtomSignature object from a string

        Parameters
        ----------
        signature : str
            The signature as a string
        """
        # Parse the string
        parts = signature.split(cls._MORGAN_SEP)
        if len(parts) == 2:
            morgans, remaining = parts[0], parts[1]
            morgans = tuple(int(bit) for bit in morgans.split(cls._BIT_SEP))

        else:
            morgans, remaining = None, parts[0]

        if cls._NEIG_SEP in remaining:
            root = None
            root_minus, neighbors_str = remaining.split(cls._NEIG_SEP, 1)
            neighbors = [
                (bond_sig.split(cls._BOND_SEP)[0], bond_sig.split(cls._BOND_SEP)[1])
                for bond_sig in neighbors_str.split(cls._NEIG_SEP)
            ]
        else:
            root_minus = None
            root, neighbors = remaining, []

        # Build the AtomSignature instance
        instance = cls()
        instance._morgans = morgans
        instance._root = root
        instance._root_minus = root_minus
        instance._neighbors = neighbors

        return instance

    def to_mol(self) -> Chem.Mol:
        """Return the atom signature as a molecule

        Returns
        -------
        Chem.Mol
            The atom signature as a molecule
        """
        smarts = self.root.replace(";", "")  # RDkit does not like semicolons in SMARTS

        mol = Chem.MolFromSmarts(smarts)

        # Update properties
        if mol.NeedsUpdatePropertyCache():
            mol.UpdatePropertyCache()

        return mol

    @classmethod
    def atom_signature(
        cls,
        atom: Chem.Atom,
        radius: int = 2,
        boundary_bonds: bool = False,
        map_root: bool = True,
        rooted: bool = False,
        **kwargs: dict,
    ) -> str:
        """Generate a signature for an atom

        This function generates a signature for an atom based on its environment
        up to a given radius. The signature is either represented as a SMARTS
        string (smarts=True) or a SMILES string (smarts=False). The atom is
        labeled as 1.

        Parameters
        ----------
        atom : Chem.Atom
            The atom to generate the signature for.
        radius : int
            The radius of the environment to consider. If negative, the whole
            molecule is considered.
        boundary_bonds : bool
            Whether to use boundary bonds at the border of the radius. This
            option is only available for SMILES syntax.
        map_root : bool
            Whether to map the root atom in the signature. If yes, the root atom
            is labeled as 1.
        rooted : bool
            Whether to use rooted SMARTS/SMILES syntax for the signature. If yes, the
            signature is rooted at the root atom.
        **kwargs
            Additional arguments to pass to Chem.MolFragmentToSmiles calls.

        Returns
        -------
        str
            The atom signature
        """
        # Get the parent molecule
        mol = atom.GetOwningMol()

        # If radius is negative, consider the whole molecule
        if radius < 0:
            radius = mol.GetNumAtoms()

        # Generate atom symbols
        for _atom in mol.GetAtoms():
            _atom_map = 1 if _atom.GetIdx() == atom.GetIdx() and map_root else 0
            _atom_symbol = atom_to_smarts(_atom, _atom_map)
            _atom.SetProp("atom_symbol", _atom_symbol)

        # Get the bonds at the border of the radius
        bonds_radius = Chem.FindAtomEnvironmentOfRadiusN(mol, radius, atom.GetIdx())
        bonds_radius_plus = Chem.FindAtomEnvironmentOfRadiusN(mol, radius + 1, atom.GetIdx())
        bonds = [b for b in bonds_radius_plus if b not in bonds_radius]

        # Fragment the molecule
        if len(bonds) > 0:
            # Fragment the molecule
            fragmented_mol = Chem.FragmentOnBonds(
                mol,
                bonds,
                addDummies=True if boundary_bonds else False,
                dummyLabels=[(0, 0) for _ in bonds],  # Do not label the dummies
            )
        else:  # No bonds to cut
            fragmented_mol = mol

        # Retrieve the rooted fragment from amongst all the fragments
        frag_to_mol_atom_mapping = []  # Mapping of atom indexes between original and fragments
        for _frag_idx, _fragment in enumerate(
            Chem.GetMolFrags(
                fragmented_mol,
                asMols=True,
                sanitizeFrags=False,
                fragsMolAtomMapping=frag_to_mol_atom_mapping,
            )
        ):
            if atom.GetIdx() in frag_to_mol_atom_mapping[_frag_idx]:
                fragment = _fragment
                frag_to_mol_atom_mapping = frag_to_mol_atom_mapping[_frag_idx]  # Dirty..
                atom_in_frag_index = frag_to_mol_atom_mapping.index(
                    atom.GetIdx()
                )  # Atom index in the fragment
                break

        # Set a canonical atom mapping
        if fragment.NeedsUpdatePropertyCache():
            fragment.UpdatePropertyCache(strict=False)

        # Collect SMARTS elements
        _atoms_to_use = list(range(fragment.GetNumAtoms()))
        _atoms_symbols = [atom.GetProp("atom_symbol") for atom in fragment.GetAtoms()]

        # Set a canonical atom mapping
        if fragment.NeedsUpdatePropertyCache():
            fragment.UpdatePropertyCache(strict=False)
        canonical_map_fragment(fragment, _atoms_to_use, _atoms_symbols)

        # Rebuild the fragment using the computed atom symbols
        _fragment = Chem.RWMol(fragment)
        for _atom_idx in range(_fragment.GetNumAtoms()):
            _atom = _fragment.GetAtomWithIdx(_atom_idx)
            _atom_symbol = _atom.GetProp("atom_symbol")
            _fragment.ReplaceAtom(
                _atom_idx,
                Chem.AtomFromSmarts(_atom_symbol),
                updateLabel=False,
                preserveProps=False,
            )
            # Restore properties
            _fragment.GetAtomWithIdx(_atom_idx).SetProp(
                "atom_symbol", _atom_symbol
            )  # Restore the atom symbol
        fragment = _fragment.GetMol()

        if fragment.NeedsUpdatePropertyCache():
            fragment.UpdatePropertyCache(strict=False)

        # DEBUG
        # for idx in range(fragment.GetNumAtoms()):
        #     _atom = fragment.GetAtomWithIdx(idx)
        #     logging.debug(
        #         f"idx: {_atom.GetIdx():2} "
        #         f"symbol: {_atom.GetSymbol():2} "
        #         f"map: {_atom.GetAtomMapNum():2} "
        #         f"degree: {_atom.GetDegree():1} "
        #         f"connec: {_atom.GetTotalDegree():1} "
        #         f"arom: {_atom.GetIsAromatic():1} "
        #         f"smarts: {_atom.GetSmarts():20} "
        #         f"stored smarts: {_atom.GetProp('atom_symbol'):20}"
        #     )

        smarts = Chem.MolFragmentToSmiles(
            fragment,
            atomsToUse=_atoms_to_use,
            atomSymbols=_atoms_symbols,
            isomericSmiles=kwargs.get("isomericSmiles", True),
            allBondsExplicit=kwargs.get("allBondsExplicit", True),
            allHsExplicit=kwargs.get("allHsExplicit", False),
            kekuleSmiles=kwargs.get("kekuleSmiles", False),
            canonical=True,
            rootedAtAtom=atom_in_frag_index if rooted else -1,
        )

        # Return the SMARTS
        return smarts

    @classmethod
    def atom_signature_neighbors(
        cls,
        atom: Chem.Atom,
        radius: int = 1,
        boundary_bonds: bool = False,
        map_root: bool = True,
        rooted: bool = False,
        **kwargs: dict,
    ) -> List[Tuple[str, str]]:
        """Compute the « with neighbors » signature flavor fo an atom

        Parameters
        ----------
        atom : Chem.Atom
            The root atom to consider.
        radius : int
            The radius of the environment to consider.

        Returns
        -------
        None
        """
        neighbors = []
        for neighbor_atom in atom.GetNeighbors():
            neighbor_sig = cls.atom_signature(
                neighbor_atom,
                radius,
                boundary_bonds,
                map_root,
                rooted,
                **kwargs,
            )

            assert neighbor_sig != "", "Empty signature for neighbor"

            bond = atom.GetOwningMol().GetBondBetweenAtoms(atom.GetIdx(), neighbor_atom.GetIdx())
            neighbors.append((str(bond.GetBondType()), neighbor_sig))
        neighbors.sort()

        return neighbors

    def post_compute_neighbors(self, radius: int = 2) -> None:
        """Compute the neighbors signature of the atom from the signature of the root atom

        Parameters
        ----------
        radius : int
            The radius of be used (usually radius - 1 compared to the root signature)

        Returns
        -------
        None
        """
        # Get molecule from the root signature
        mol = self.to_mol()

        # Get the root atom
        for _atom in mol.GetAtoms():
            if _atom.GetAtomMapNum() == 1:
                root_atom = _atom
                break

        # Compute the root signature at radius
        self._root_minus = self.atom_signature(
            root_atom,
            radius - 1,
        )

        # Compute the neighbors signatures at radius - 1
        self._neighbors = self.atom_signature_neighbors(
            root_atom,
            radius - 1,
        )


# =================================================================================================
# Atom Signature Helper Functions
# =================================================================================================


def get_smarts_features(qatom: Chem.Atom, wish_list=None) -> dict:
    """Get the features of a SMARTS query atom

    Parameters
    ----------
    qatom : Chem.Atom
        The SMARTS query atom
    wish_list : list
        The list of features to extract. If None, all features are extracted.
        The list of features is:
        - # : Atomic number
        - A : Aliphatic
        - a : Aromatic
        - H : Total number of hydrogens (implicit + explicit)
        - h : Number of implicit hydrogens
        - D : Degree
        - X : Connectivity
        - +-: Charge

    Returns
    -------
    dict
        The features of the SMARTS query atom
    """
    # Get the atom properties from the descriptor
    feats = {}
    _descriptors = qatom.DescribeQuery()

    if wish_list is None:
        wish_list = ["#", "A", "a", "H", "h", "D", "X", "+-"]

    # Atomic number and atom type
    if "#" in wish_list:

        # Atomic number
        _match = re.search(r"AtomAtomicNum (?P<value>\d+) = val", _descriptors)
        if _match:
            feats["#"] = int(_match.group("value"))

        # Atom Type (see getAtomListQueryVals from rdkit/Code/GraphMol/QueryOps.cpp)
        _match = re.search(r"AtomType (?P<value>\d+) = val", _descriptors)
        if _match:
            if int(_match.group("value")) > 1000:  # Atom is aromatic
                _atom_number = int(_match.group("value")) - 1000
                if "#" in feats:
                    assert feats["#"] == _atom_number
                feats["#"] = _atom_number
                feats["a"] = 1
            else:  # Atom is aliphatic
                _atom_number = int(_match.group("value"))
                if "#" in feats:
                    assert feats["#"] == _atom_number
                feats["#"] = int(_match.group("value"))
                feats["A"] = 1

    # Hydrogens (implicit + explicit)
    if "H" in wish_list:
        _match = re.search(r"AtomHCount (?P<value>\d) = val", _descriptors)
        if _match:
            feats["H"] = int(_match.group("value"))

    # Implicit hydrogens
    if "h" in wish_list:
        _match = re.search(r"AtomImplicitHCount (?P<value>\d) = val", _descriptors)
        if _match:
            feats["h"] = int(_match.group("value"))

    # # Aromatic
    if "a" in wish_list and "a" not in feats:
        _match = re.search(r"AtomIsAromatic (?P<value>\d) = val", _descriptors)
        if _match:
            feats["a"] = int(_match.group("value"))

    # Aliphatic
    if "A" in wish_list and "A" not in feats:
        _match = re.search(r"AtomIsAliphatic (?P<value>\d) = val", _descriptors)
        if _match:
            feats["A"] = int(_match.group("value"))

    # Degree
    if "D" in wish_list:
        _match = re.search(r"AtomExplicitDegree (?P<value>\d) = val", _descriptors)
        if _match:
            feats["D"] = int(_match.group("value"))

    # Connectivity
    if "X" in wish_list:
        _match = re.search(r"AtomTotalDegree (?P<value>\d) = val", _descriptors)
        if _match:
            feats["X"] = int(_match.group("value"))

    # Charge
    if "+-" in wish_list:
        _match = re.search(r"AtomFormalCharge (?P<value>-?\d) = val", _descriptors)
        if _match:
            feats["+-"] = int(_match.group("value"))

    return feats


def atom_to_smarts(atom: Chem.Atom, atom_map: int = 0) -> str:
    """Generate a SMARTS string for an atom

    Parameters
    ----------
    atom : Chem.Atom
        The atom to generate the SMARTS for
    atom_map : int
        The atom map number to use in the SMARTS string. If 0 (default), the
        atom map number is not used.

    Returns
    -------
    str
        The SMARTS string
    """

    _PROP_SEP = ";"

    # Directly get features from the query atom
    if isinstance(atom, Chem.QueryAtom):
        feats = get_smarts_features(atom)
        _number = feats.get("#", 0)
        _symbol = Chem.GetPeriodicTable().GetElementSymbol(_number)
        _H_count = feats.get("H", 0)
        _h_count = feats.get("h", 0)
        _connectivity = feats.get("X", 0)
        _degree = feats.get("D", 0)
        _formal_charge = feats.get("+-", 0)
        # _is_aromatic = feats.get("a", 0)
    else:
        _symbol = atom.GetSymbol()
        _H_count = atom.GetTotalNumHs()  # Total Hs, including implicit Hs
        _h_count = atom.GetNumImplicitHs()  # Implicit Hs
        _connectivity = atom.GetTotalDegree()  # Connections, including H
        _degree = atom.GetDegree()  # Explicit connections, excluding implict Hs
        _formal_charge = atom.GetFormalCharge()
        # _is_aromatic = atom.GetIsAromatic()

    # Special case for dummies
    if atom.GetAtomicNum() == 0:
        return "*"

    # Refine symbols
    if atom.GetIsAromatic():
        _symbol = _symbol.lower()
    elif atom.GetAtomicNum() == 1:
        _symbol = "#1"  # otherwise, H is not recognized

    # Assemble the SMARTS
    smarts = f"[{_symbol}"
    smarts += f"{_PROP_SEP}H{_H_count}"
    smarts += f"{_PROP_SEP}h{_h_count}"
    smarts += f"{_PROP_SEP}D{_degree}"
    smarts += f"{_PROP_SEP}X{_connectivity}"
    # if _is_aromatic:
    #     smarts += f"{_PROP_SEP}a"
    # else:
    #     smarts += f"{_PROP_SEP}A"
    if _formal_charge > 0:
        if _formal_charge == 1:
            smarts += f"{_PROP_SEP}+"
        else:
            smarts += f"{_PROP_SEP}+{_formal_charge}"
    elif _formal_charge < 0:
        if _formal_charge == -1:
            smarts += f"{_PROP_SEP}-"
        else:
            smarts += f"{_PROP_SEP}-{abs(_formal_charge)}"
    if atom_map != 0:
        smarts += f":{atom_map}"
    smarts += "]"

    return smarts


def bond_to_smarts(bond: Chem.Bond, use_stereo: bool = False) -> str:
    """Generate a SMARTS string for a bond

    Parameters
    ----------
    bond : Chem.Bond
        The bond to generate the SMARTS for.
    use_stereo : bool
        Whether to use and express stereochemistry information.

    Returns
    -------
    str
        The SMARTS string
    """
    bond_type = bond.GetBondType()
    match bond_type:
        case Chem.BondType.SINGLE:
            if use_stereo:
                bond_dir = bond.GetBondDir()
                match bond_dir:
                    case Chem.BondDir.ENDDOWNRIGHT:
                        return "\\"
                    case Chem.BondDir.ENDUPRIGHT:
                        return "/"
                    case _:
                        return "-"
            else:
                return "-"
        case Chem.BondType.DOUBLE:
            return "="
        case Chem.BondType.TRIPLE:
            return "#"
        case Chem.BondType.QUADRUPLE:
            return "$"
        case Chem.BondType.AROMATIC:
            bond_dir = bond.GetBondDir()
            match bond_dir:
                case Chem.BondDir.ENDDOWNRIGHT:
                    return ":\\"
                case Chem.BondDir.ENDUPRIGHT:
                    return ":/"
                case _:
                    return ":"
        case Chem.BondType.DATIVE:
            return "-"
        case _:
            return "~"


def canonical_map_fragment(
    mol: Chem.Mol,
    atoms_to_use: list,
    atoms_symbols: list = None,
) -> None:
    """Canonize the atom map numbers of a molecule fragment

    This function canonizes the atom map numbers of a molecule fragment.

    Parameters
    ----------
    mol : Chem.Mol
        The molecule to canonicalize the atom map numbers for.
    atoms_to_use : list
        The list of atom indexes to use in the fragment.

    Returns
    -------
    None
    """
    ranks = list(
        Chem.CanonicalRankAtomsInFragment(
            mol, atomsToUse=atoms_to_use, atomSymbols=atoms_symbols, includeAtomMaps=False
        )
    )
    for j, i in enumerate(ranks):
        if j in atoms_to_use:
            mol.GetAtomWithIdx(j).SetIntProp("molAtomMapNumber", i + 1)


# =================================================================================================
# Molecule Signature
# =================================================================================================


class MoleculeSignature:
    """Class representing the signature of a molecule.

    The signature of a molecule is composed of the signature of its atoms.
    """

    _ATOM_SEP = " .. "  # Separator between atom signatures

    def __init__(
        self,
        mol: Chem.Mol = None,
        radius: int = 2,
        nbits: int = 2048,
        use_stereo: bool = True,
        boundary_bonds: bool = False,
        map_root: bool = True,
        rooted: bool = False,
        **kwargs: dict,
    ) -> None:
        """Initialize the MoleculeSignature object

        Parameters
        ----------
        mol : Chem.Mol
            The molecule to generate the signature for.
        radius : int
            The radius of the environment to consider.
        nbits : int
            The number of bits to use for the Morgan fingerprint. If 0, no
            Morgan fingerprint is computed.
        use_stereo : bool
            Whether to use and express stereochemistry information.
        boundary_bonds : bool
            Whether to add bonds at the boundary of the radius.
        map_root : bool
            Whether to map root atoms in atom signatures. If yes, root atoms are
            labeled as 1.
        rooted : bool
            Whether to use rooted SMARTS/SMILES syntax within atom signatures. If yes,
            signatures are rooted at the root atoms.
        **kwargs
            Additional arguments to pass to Chem.MolFragmentToSmiles calls.
        """
        # Deprecation warnings
        if "nBits" in kwargs:
            logger.warning("nBits is deprecated, use nbits instead.")
            nbits = kwargs.pop("nBits")
        if "all_bits" in kwargs:
            logger.warning("all_bits option is deprecated, it will be removed soon.")

        # Check arguments
        if mol is None:
            return
        else:
            assert isinstance(mol, Chem.Mol), "mol must be a RDKit molecule object"

        # Parameters reminder
        self.kwargs = clean_kwargs(kwargs)
        self._atoms = []

        # Get Morgan bits
        if nbits > 0:
            # Prepare recipient to collect bits information
            bits_info = rdFingerprintGenerator.AdditionalOutput()
            bits_info.AllocateAtomToBits()

            # Compute Morgan bits
            rdFingerprintGenerator.GetMorganGenerator(
                radius=radius,
                fpSize=nbits,
                includeChirality=use_stereo,
            ).GetFingerprint(mol, additionalOutput=bits_info)

            # Get the Morgan bits per atom
            morgan_vect = bits_info.GetAtomToBits()

        else:
            morgan_vect = [None] * mol.GetNumAtoms()

        # Flatten the molecule
        mol_flat = flat_molecule_copy(mol)

        # Get indexes mapping between original vs flattened molecules
        index_mapping = get_index_mapping(mol, mol_flat)  # key: mol_flat => value: mol

        # Reorder morgan_vect
        morgan_vect = [morgan_vect[index_mapping[idx]] for idx in range(len(morgan_vect))]

        # Compute the signatures of all atoms
        for atom in mol_flat.GetAtoms():
            _morgan_bits = morgan_vect[atom.GetIdx()]
            _sig = AtomSignature(
                atom,
                radius,
                _morgan_bits,
                boundary_bonds,
                map_root,
                rooted,
                **self.kwargs,
            )
            if _sig != "":  # only collect non-empty signatures
                self._atoms.append(_sig)

        assert len(self._atoms) > 0, "No atom signature found"

        # Sort the atom signatures
        self._atoms.sort()

    def __repr__(self) -> str:
        _ = "MoleculeSignature("
        _ += f"atoms={self.atoms}"
        _ += ")"
        return _

    def __len__(self) -> int:
        return len(self._atoms)

    def __str__(self) -> str:
        return self.to_string()

    def __eq__(self, other) -> bool:
        if not isinstance(other, MoleculeSignature):
            return False
        return (
            self.atoms == other.atoms
            and self.root_minus == other.root_minus
            and self.neighbors == other.neighbors
            and self.morgans == other.morgans
        )

    @property
    def atoms(self) -> list:
        return [atom for atom in self._atoms]

    @property
    def roots(self) -> list:
        return [atom.root for atom in self._atoms]

    @property
    def root_minus(self) -> list:
        return [atom.root_minus for atom in self._atoms]

    @property
    def neighbors(self) -> list:
        return [atom.neighbors for atom in self._atoms]

    @property
    def morgans(self) -> list:
        return [atom.morgans for atom in self._atoms]

    def to_list(self, neighbors=False, morgans=True) -> list:
        """Return the signature as a list of features.

        If neighbors is False, the signature of the root atom at full radius is
        used. If neighbors is True, the signature of the root atom at radius - 1
        is used, followed by the atom signature of the neighbors at radius - 1.

        Parameters
        ----------
        neighbors : bool
            Whether to include neighbors.
        morgans : bool
            Whether to include Morgan bits.

        Returns
        -------
        list
            The signature as a list
        """
        return [atom.to_string(neighbors=neighbors, morgans=morgans) for atom in self._atoms]

    def to_string(self, neighbors=False, morgans=True) -> str:
        """Return the signature as a string.

        If neighbors is False, the signature of the root atum at full radius is
        used. If neighbors is True, the signature of the root atom at radius - 1
        is used, followed by the atom signature of the neighbors at radius - 1.

        Parameters
        ----------
        neighbors : bool
            Whether to include the neighbors.
        morgans : bool
            Whether to include the Morgan bits.

        Returns
        -------
        str
            The signature as a string
        """
        return self._ATOM_SEP.join(self.to_list(neighbors=neighbors, morgans=morgans))

    @classmethod
    def from_list(cls, signatures: list) -> None:
        """Initialize the MoleculeSignature object from a list

        Parameters
        ----------
        signatures : list
            The list of signatures as strings
        """
        # Parse the list
        atoms = [AtomSignature.from_string(sig) for sig in signatures]

        # Build the MoleculeSignature instance
        instance = cls()
        instance._atoms = atoms

        return instance

    @classmethod
    def from_string(cls, signature: str) -> None:
        """Initialize the MoleculeSignature object from a string

        Parameters
        ----------
        signature : str
            The signature as a string
        """
        signatures = signature.split(cls._ATOM_SEP)
        return cls.from_list(signatures)

    def post_compute_neighbors(self, radius: int = 2) -> None:
        """Compute the neighbors signature of the atoms from the signature of the root atom

        Parameters
        ----------
        signatures : list
            The list of atom signatures
        radius : int
            The radius of be used (usually radius - 1 compared to the root signature)

        Returns
        -------
        None
        """
        [_atom.post_compute_neighbors(radius) for _atom in self._atoms]


# =================================================================================================
# Molecule Signature helper functions
# =================================================================================================
def flat_molecule_copy(mol: Chem.Mol) -> Chem.Mol:
    """Create a flat copy of a molecule

    Notes:
    - original molecule is not modified
    - unneeded Hs are removed

    Parameters
    ----------
    mol : Chem.Mol
        The molecule to create a flat copy of.

    Returns
    -------
    Chem.Mol
        The flat copy of the molecule.
    """
    _mol = Chem.Mol(mol)  # Work on a copy
    Chem.RemoveStereochemistry(_mol)  # Remove stereochemistry
    # _mol = Chem.RemoveHs(_mol)        # Remove Hs not being useful anymore
    # Go back and forth with SMILES to get rid of explicit Hs
    # Note: just using Chem.RemoveHs() does not update the implicit H count of atoms
    _mol = Chem.MolFromSmiles(Chem.MolToSmiles(_mol))

    return _mol


def get_index_mapping(mol1: Chem.Mol, mol2: Chem.Mol, includeChirality: bool = False) -> dict:
    """Get the index mapping between two molecules

    This function computes the index mapping between two molecules.

    Parameters
    ----------
    mol1 : Chem.Mol
        The first molecule
    mol2 : Chem.Mol
        The second molecule
    includeChirality : bool
        Whether to include chirality information

    Returns
    -------
    dict
        The index mapping between the two molecules as a dictionary where the
        keys are the indexes of the second molecule and the values are the indexes
        of the second molecule.
    """
    canon_order_mol1 = list(Chem.CanonicalRankAtoms(mol1, includeChirality=includeChirality))
    canon_order_mol2 = list(Chem.CanonicalRankAtoms(mol2, includeChirality=includeChirality))
    index_mapping = {}
    for idx_mol1, rank_mol1 in enumerate(canon_order_mol1):
        idx_mol2 = canon_order_mol2.index(rank_mol1)
        index_mapping[idx_mol2] = idx_mol1
    return index_mapping


# =================================================================================================
# Overall helper functions
# =================================================================================================


def clean_kwargs(kwargs: dict) -> dict:
    """Check the kwargs dictionary for valid arguments

    This function checks the kwargs dictionary for valid arguments and returns a
    cleaned version of the dictionary.

    Parameters
    ----------
    kwargs : dict
        The dictionary of keyword arguments

    Returns
    -------
    dict
        The cleaned dictionary of keyword arguments
    """
    # Initialize the cleaned dictionary
    cleaned_kwargs = {}

    # Check for valid arguments
    for key, value in kwargs.items():
        if key in [
            "isomericSmiles",
            "allBondsExplicit",
            "allHsExplicit",
            "kekuleSmiles",
        ]:
            cleaned_kwargs[key] = value
        else:
            logger.warning(f"Invalid argument: {key} (value: {value}), skipping argument.")

    return cleaned_kwargs
