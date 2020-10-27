import os
from typing import Optional

from gtdbtk.config.output import TRANSLATION_TABLE_SUFFIX
from gtdbtk.exceptions import GTDBTkExit


class TlnTableFile(object):
    """The translation table summary file generated by each genome.."""

    def __init__(self, out_dir: str, gid: str,
                 best_tln_table: Optional[int] = None,
                 coding_density_4: Optional[float] = None,
                 coding_density_11: Optional[float] = None):
        self.path = self.get_path(out_dir, gid)
        self._best_tln_table = best_tln_table
        self._coding_density_4 = coding_density_4
        self._coding_density_11 = coding_density_11

    @property
    def best_tln_table(self):
        return self._best_tln_table

    @best_tln_table.setter
    def best_tln_table(self, v):
        try:
            self._best_tln_table = int(v)
        except ValueError:
            raise GTDBTkExit(f'Invalid translation table: {v} for {self.path}')

    @property
    def coding_density_4(self):
        return self._coding_density_4

    @coding_density_4.setter
    def coding_density_4(self, v):
        try:
            self._coding_density_4 = int(v)
        except ValueError:
            raise GTDBTkExit(f'Invalid coding density: {v} for {self.path}')

    @property
    def coding_density_11(self):
        return self._coding_density_11

    @coding_density_11.setter
    def coding_density_11(self, v):
        try:
            self._coding_density_11 = int(v)
        except ValueError:
            raise GTDBTkExit(f'Invalid coding density: {v} for {self.path}')

    @staticmethod
    def get_path(out_dir: str, gid: str):
        # return os.path.join(out_dir, f'{gid}{TRANSLATION_TABLE_SUFFIX}')
        # TODO: One day this should use the above, will probably break other workflows.
        return os.path.join(out_dir, f'prodigal{TRANSLATION_TABLE_SUFFIX}')

    def read(self):
        with open(self.path, 'r') as fh:
            for line in fh.readlines():
                idx, val = line.strip().split('\t')
                if idx == 'best_translation_table':
                    self.best_tln_table = val
                elif idx == 'coding_density_4':
                    self.coding_density_4 = val
                elif idx == 'coding_density_11':
                    self.coding_density_11 = val

    def write(self):
        with open(self.path, 'w') as fh:
            fh.write(f'best_translation_table\t{self.best_tln_table}\n')
            fh.write(f'coding_density_4\t{self.coding_density_4}\n')
            fh.write(f'coding_density_11\t{self.coding_density_11}\n')
