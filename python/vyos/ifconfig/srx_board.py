# Copyright VyOS maintainers and contributors <maintainers@vyos.io>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library.  If not, see <http://www.gnu.org/licenses/>.

"""Helpers for boards without DMI (Juniper SRX300, Octeon MIPS).

Kept out of interface.py so the platform logic does not touch upstream code.
"""


def machine_id() -> str:
    """Stable per-installation ID when dmidecode/DMI is unavailable."""
    try:
        with open('/etc/machine-id') as f:
            return f.read().strip()
    except OSError:
        return ''
