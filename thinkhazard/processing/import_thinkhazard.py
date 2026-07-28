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

        # Pre-load all administrative divisions into a cache keyed by id to
        # avoid one DB round-trip per CSV row.
        division_cache: dict = {
            d.id: d
            for d in self.dbsession.query(AdministrativeDivision).all()
        }

        # Pre-load existing associations into a set so duplicate checks do not
        # require a per-row query.
        existing_associations: set = {
            (a.administrativedivision_id, a.hazardcategory_id)
            for a in self.dbsession.query(
                HazardCategoryAdministrativeDivisionAssociation
            ).all()
        }

        # Local cache for HazardCategory lookups; there are only O(types×levels)
        # unique combinations so this stays very small.
        hazard_category_cache: dict = {}

        new_associations = []

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

                try:
                    admin_id_int = int(admin_id)
                except ValueError:
                    LOG.warning(
                        "Invalid admin division id '%s' (expected integer), skipping.",
                        admin_id,
                    )
                    skipped += 1
                    continue

                division = division_cache.get(admin_id_int)
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

                cache_key = (hazardtype_mnemonic, hazardlevel_mnemonic)
                if cache_key not in hazard_category_cache:
                    hazard_category_cache[cache_key] = HazardCategory.get(
                        self.dbsession, hazardtype_mnemonic, hazardlevel_mnemonic
                    )
                hazardcategory = hazard_category_cache[cache_key]
                if hazardcategory is None:
                    LOG.warning(
                        "HazardCategory (%s/%s) not found, skipping.",
                        hazardtype_mnemonic,
                        hazardlevel_mnemonic,
                    )
                    skipped += 1
                    continue

                assoc_key = (division.id, hazardcategory.id)
                if assoc_key not in existing_associations:
                    new_associations.append(
                        HazardCategoryAdministrativeDivisionAssociation(
                            administrativedivision_id=division.id,
                            hazardcategory_id=hazardcategory.id,
                        )
                    )
                    existing_associations.add(assoc_key)
                    LOG.debug(
                        "Created association: division=%s hazard=%s/%s",
                        admin_id,
                        hazardtype_mnemonic,
                        hazardlevel_mnemonic,
                    )
                    imported += 1
                else:
                    LOG.debug(
                        "Association already exists: division=%s hazard=%s/%s, skipping.",
                        admin_id,
                        hazardtype_mnemonic,
                        hazardlevel_mnemonic,
                    )

        # Bulk-insert all new associations in chunks to minimise round-trips.
        chunk_size = 5000
        for i in range(0, len(new_associations), chunk_size):
            chunk = new_associations[i : i + chunk_size]
            self.dbsession.bulk_save_objects(chunk, return_defaults=False)
            self.dbsession.flush()

        LOG.info(
            "Import complete: %d rows imported, %d rows skipped.", imported, skipped
        )
