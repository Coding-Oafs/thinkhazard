# -*- coding: utf-8 -*-
#
# Copyright (C) 2015-2017 by the GFDRR / World Bank
#
# This file is part of ThinkHazard.
#
# ThinkHazard is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.
#
# ThinkHazard is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for
# more details.
#
# You should have received a copy of the GNU General Public License along with
# ThinkHazard.  If not, see <http://www.gnu.org/licenses/>.

import csv
import logging

from thinkhazard.processing import BaseProcessor
from thinkhazard.models import (
    AdministrativeDivision,
    HazardCategory,
    HazardCategoryAdministrativeDivisionAssociation,
    HazardLevel,
    HazardType,
)

LOG = logging.getLogger(__name__)


class ThinkhazardImporter(BaseProcessor):
    """Imports hazard-level assignments exported via the admin
    ``/admin/admindiv_hazardsets/export`` endpoint.

    The expected CSV format is::

        hazardtype,code,name,hazard_level

    where *code* is the integer primary key of an
    :class:`AdministrativeDivision` row and *hazardtype* / *hazard_level* are
    mnemonics (e.g. ``FL`` / ``HIG``).
    """

    @staticmethod
    def argument_parser():
        parser = BaseProcessor.argument_parser()
        parser.add_argument(
            "--input",
            dest="input",
            required=True,
            help="Path to the CSV file exported from the ThinkHazard admin interface.",
        )
        return parser

    def do_execute(self, input, **kwargs):
        imported = 0
        skipped = 0

        with open(input, newline="", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                hazardtype_mnemonic = row.get("hazardtype", "").strip()
                admin_id = row.get("code", "").strip()
                hazardlevel_mnemonic = row.get("hazard_level", "").strip()

                if not hazardtype_mnemonic or not admin_id or not hazardlevel_mnemonic:
                    LOG.warning("Skipping incomplete row: %s", row)
                    skipped += 1
                    continue

                division = (
                    self.dbsession.query(AdministrativeDivision)
                    .filter(AdministrativeDivision.id == int(admin_id))
                    .one_or_none()
                )
                if division is None:
                    LOG.warning(
                        "AdministrativeDivision with id=%s not found, skipping.",
                        admin_id,
                    )
                    skipped += 1
                    continue

                hazardtype = HazardType.get(self.dbsession, hazardtype_mnemonic)
                if hazardtype is None:
                    LOG.warning(
                        "HazardType '%s' not found, skipping.", hazardtype_mnemonic
                    )
                    skipped += 1
                    continue

                hazardlevel = HazardLevel.get(self.dbsession, hazardlevel_mnemonic)
                if hazardlevel is None:
                    LOG.warning(
                        "HazardLevel '%s' not found, skipping.", hazardlevel_mnemonic
                    )
                    skipped += 1
                    continue

                hazardcategory = HazardCategory.get(
                    self.dbsession, hazardtype_mnemonic, hazardlevel_mnemonic
                )
                if hazardcategory is None:
                    LOG.warning(
                        "HazardCategory (%s/%s) not found, skipping.",
                        hazardtype_mnemonic,
                        hazardlevel_mnemonic,
                    )
                    skipped += 1
                    continue

                # Check for an existing association and update, or create new
                existing = (
                    self.dbsession.query(HazardCategoryAdministrativeDivisionAssociation)
                    .filter_by(
                        administrativedivision_id=division.id,
                        hazardcategory_id=hazardcategory.id,
                    )
                    .one_or_none()
                )
                if existing is None:
                    association = HazardCategoryAdministrativeDivisionAssociation(
                        administrativedivision_id=division.id,
                        hazardcategory_id=hazardcategory.id,
                    )
                    self.dbsession.add(association)
                    LOG.debug(
                        "Created association: division=%s hazard=%s/%s",
                        admin_id,
                        hazardtype_mnemonic,
                        hazardlevel_mnemonic,
                    )

                imported += 1

        LOG.info(
            "Import complete: %d rows imported, %d rows skipped.", imported, skipped
        )
