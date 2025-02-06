# Molecule Signature

[![Github Version](https://img.shields.io/github/v/release/brsynth/molecule-signature?display_name=tag&sort=semver)](version)
[![Github Licence](https://img.shields.io/github/license/brsynth/molecule-signature)](LICENSE.md)
![Unit Test Coverage](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/tduigou/056fdf29a6c0ab5b61a62f21468be178/raw/molecule-signature-coverage.json)

Signature-based enumeration of molecules from morgan fingerprints.

## Table of Contents

- [Molecule Signature](#molecule-signature)
  - [Table of Contents](#table-of-contents)
  - [Installation](#installation)
    - [From conda package](#from-conda-package)
    - [From source code](#from-source-code)
  - [Usage](#usage)
    - [Build a signature from SMILES](#build-a-signature-from-smiles)
    - [Build an alphabet](#build-an-alphabet)
    - [Enumerate molecules from a ECFP fingerprint](#enumerate-molecules-from-a-ecfp-fingerprint)
  - [Citation](#citation)

## Installation

### From conda package

Installation using conda is the easiest way to get started. First, install Conda
and then install the package from the conda-forge channel.

1. **Install Conda:**
   Download the installer for your operating system from the [Conda Installation
   page](https://docs.conda.io/projects/conda/en/latest/user-guide/install/index.html).
   Follow the instructions on the page to install Conda. For example, on
   Windows, you would download the installer and run it. On macOS and Linux, you
   might use a command like:

    ```bash
    bash ~/Downloads/Miniconda3-latest-Linux-x86_64.sh
    ```

    Follow the prompts on the installer to complete the installation.

2. **Install signature from conda-forge:**

    ```bash
    conda install -c conda-forge signature
    ```

### From source code

One can also install the tool from the source code. This method is useful for
development purposes.

1. **Install dependencies:**

    ```bash
    conda env create -f environment.yml
    ```

2. **Add the signature to conda:**

    ```bash
    conda activate sig
    pip install -e .  # From the root of the repository
    ```

3. **Add development dependencies:**

    ```bash
    conda activate sig
    conda env update -n sig -f environment-dev.yml
    ```

## Usage

### Build a signature from SMILES

Here a simple example showing how to build a signature from a SMILES string. For
more example, one can refer to the [signature-basics](notebooks/signature-basics.ipynb) notebook.

```python
from rdkit import Chem
from molsig.Signature import MoleculeSignature

mol = Chem.MolFromSmiles("CCO")
mol_sig = MoleculeSignature(mol)
mol_sig.to_list()
# [
#  '80-1410 ## [C;H3;h3;D1;X4]-[C;H2;h2;D2;X4:1]-[O;H1;h1;D1;X2]',
#  '807-222 ## [C;H3;h3;D1;X4]-[C;H2;h2;D2;X4]-[O;H1;h1;D1;X2:1]',
#  '1057-294 ## [O;H1;h1;D1;X2]-[C;H2;h2;D2;X4]-[C;H3;h3;D1;X4:1]'
# ]
```

With the command line:
```sh
molsig signature
    --input-smiles-str <SMILES>
    --output-data-tsv <Output file, tsv>
```

### Build an alphabet

Alphabet makes use of signatures to create a collection of *morgan bits*-to-*atom signature* mappings.

See the [creating-alphabet-basics](notebooks/creating-alphabet-basics.ipynb) notebook.

With the command line:
```sh
molsig alphabet
  --input-smiles-txt <SMILES>
  --parameter-radius-int [2]
  --parameter-nbits-int [2048]
  --output-alphabet-npz <Output file, npz>
```

### Enumerate molecules from a ECFP fingerprint

See the [enumeration-basics](notebooks/enumeration-basics.ipynb) notebook.

With the command line:
```sh
molsig enumerate
  --input-smiles-str <SMILES>
  --input-alphabet-npz <Input alphabet file, npz>
  --output-data-tsv <Output file, tsv>
```

## Citation

If you use this software, please cite it as below.

Meyer, P., Duigou, T., Gricourt, G., & Faulon, J.-L. Reverse Engineering Molecules from Fingerprints through Deterministic Enumeration and Generative Models. In preparation.
