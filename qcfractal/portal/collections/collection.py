"""Base Collection classes.

"""

import abc
import copy
import json
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Union

import pandas as pd
from tqdm import tqdm

from ...interface.models import ProtoModel
from ...interface.models.records import RecordBase

if TYPE_CHECKING:  # pragma: no cover
    from .. import PortalClient
    from ..models import ObjectId


class Collection(abc.ABC):
    def __init__(self, name: str, client: Optional["PortalClient"] = None, **kwargs: Any):
        """Initialize a Collection.

        Parameters
        ----------
        name : str
            The name of the Collection object; used to reference the collection on the server.
        client : PortalClient, optional
            A PortalClient connected to a server.
        **kwargs : Dict[str, Any]
            Additional keywords passed to the Collection and the initial data constructor.
            It is up to Collection subclasses to make use of that data.
        """

        self._client = client

        if (self._client is not None) and not (self._client.__class__.__name__ == "PortalClient"):
            raise TypeError("Expected PortalClient as `client` kwarg, found {}.".format(type(self._client)))

        if "collection" not in kwargs:
            kwargs["collection"] = self.__class__.__name__.lower()

        kwargs["name"] = name

        # Create the data model
        self._data = self._DataModel(**kwargs)

    class _DataModel(ProtoModel):
        """
        Internal base model typed by PyDantic.

        This structure validates input, allows server-side validation and data security,
        and puts information into a form that is passable between server and client.

        Subclasses of Collection can extend this class to supplement the data defined by the Collection.

        """

        # TODO: document each of these fields in docstring?
        id: str = "local"
        name: str

        collection: str
        provenance: Dict[str, str] = {}

        tags: List[str] = []
        tagline: Optional[str] = None
        description: Optional[str] = None

        group: str = "default"
        visibility: bool = True

        view_url_hdf5: Optional[str] = None
        view_url_plaintext: Optional[str] = None
        view_metadata: Optional[Dict[str, str]] = None
        view_available: bool = False

        metadata: Dict[str, Any] = {}

    def __str__(self) -> str:
        """
        A simple string representation of the Collection.

        Returns
        -------
        ret : str
            A representation of the Collection.

        Examples
        --------

        >>> repr(obj)
        Collection(name=`S22`, id='5b7f1fd57b87872d2c5d0a6d', client=`localhost:8888`)
        """

        client = None
        if self._client:
            client = self._client.address

        class_name = self.__class__.__name__
        ret = "{}(".format(class_name)
        ret += "name=`{}`, ".format(self._data.name)
        ret += "id='{}', ".format(self._data.id)
        ret += "client='{}') ".format(client)

        return ret

    def __repr__(self) -> str:
        return f"<{self}>"

    @abc.abstractmethod
    def __getitem__(self, spec: Union[List[str], str]):
        pass

    def _check_client(self):
        if self._client is None:
            raise AttributeError("This method requires a PortalClient and no client was set")

    @property
    def name(self) -> str:
        return self._data.name

    ## inits and export

    @classmethod
    def from_server(cls, client: "PortalClient", name: str) -> "Collection":
        """Creates a new class from a server

        Parameters
        ----------
        client : PortalClient
            A PortalClient connected to a server.
        name : str
            The name of the collection to pull from.

        Returns
        -------
        Collection
            A constructed collection.

        """

        if not (client.__class__.__name__ == "PortalClient"):
            raise TypeError("Expected a PortalClient as first argument, found {}.".format(type(client)))

        class_name = cls.__name__.lower()
        tmp_data = client.get_collection(class_name, name, full_return=True)
        if tmp_data.meta.n_found == 0:
            raise KeyError("Warning! `{}: {}` not found.".format(class_name, name))

        return cls.from_json(tmp_data.data[0], client=client)

    @classmethod
    def from_dict(cls, data: Dict[str, Any], client: "FractalClient" = None) -> "Collection":
        """Creates a new Collection instance from a dict representation.
        Allows roundtrips from `Collection.to_dict`.
        Parameters
        ----------
        data : Dict[str, Any]
            A dict to create a new Collection instance from.
        client : FractalClient, optional
            A FractalClient connected to a server.
        Returns
        -------
        Collection
            A Collection instance.
        """
        # Check we are building the correct object
        class_name = cls.__name__.lower()
        if "collection" not in data:
            raise KeyError("Attempted to create Collection from JSON, but no `collection` field found.")

        if data["collection"] != class_name:
            raise KeyError(
                "Attempted to create Collection from JSON with class {}, but found collection type of {}.".format(
                    class_name, data["collection"]
                )
            )

        name = data.pop("name")
        # Allow PyDantic to handle type validation
        ret = cls(name, client=client, **data)
        return ret

    @classmethod
    def from_json(cls, jsondata: Optional[str] = None, filename: Optional[str] = None, client: "FractalClient" = None) -> "Collection":
        """Creates a new Collection instance from a JSON string.
        Allows roundtrips from `Collection.to_json`.
        One of `jsondata` or `filename` must be provided.
        Parameters
        ----------
        jsondata : str, Optional, Default: None
            The JSON string to create a new Collection instance from.
        filename : str, Optional, Default: None
            The filename to read JSON data from.
        client : FractalClient, optional
            A FractalClient connected to a server.
        Returns
        -------
        Collection
            A Collection instance.
        """
        if (jsondata is not None) and (filename is not None):
            raise ValueError("One of `jsondata` or `filename` must be specified, not both")

        if jsondata is not None:
            data = json.loads(jsondata)
        elif filename is not None:
            with open(filename, 'r') as jsonfile:
                data = json.load(jsonfile)
        else:
            raise ValueError("One of `jsondata` or `filename` must be specified")

        return cls.from_dict(data, client)

    def to_dict(self):
        """
        Returns a copy of the current Collection data as a Python dict.
        Returns
        -------
        ret : dict
            A Python dict representation of the Collection data.
        """
        datadict = self.data.dict()
        return copy.deepcopy(datadict)

    def to_json(self, filename: Optional[str] = None):
        """
        If a filename is provided, dumps the file to disk.
        Otherwise returns data as a JSON string.
        Parameters
        ----------
        filename : str, Optional, Default: None
            The filename to write JSON data to.
        Returns
        -------
        ret : dict
            If `filename=None`, a JSON representation of the Collection.
            Otherwise `None`.
        """
        jsondata = self.json()
        if filename is not None:
            with open(filename, "w") as open_file:
                open_file.write(jsondata)
        else:
            return jsondata

    ## entry touchpoints

    @abc.abstractproperty
    @property
    def entry_names(self):
        pass

    @abc.abstractproperty
    @property
    def entries(self):
        pass

    @abc.abstractmethod
    def list_entries(self):
        pass

    @abc.abstractmethod
    def get_entry(self):
        pass

    @abc.abstractmethod
    def add_entry(self):
        pass

    ## spec touchpoints

    @abc.abstractproperty
    @property
    def spec_names(self):
        pass

    @abc.abstractproperty
    @property
    def specs(self):
        pass

    @abc.abstractmethod
    def list_specs(self):
        pass

    @abc.abstractmethod
    def get_spec(self):
        pass

    @abc.abstractmethod
    def add_spec(self):
        pass

    ## record touchpoints

    @abc.abstractmethod
    def get_record(self, entry_name, spec_name):
        pass

    @abc.abstractproperty
    def loc(self):
        pass

    @abc.abstractproperty
    def iter(self):
        pass

    ## server interaction

    @abc.abstractmethod
    def _pre_sync_prep(self, client: "PortalClient"):
        """Additional actions to take before syncing, done as the last step before data is written.

        This does not return anything but can prep the `self._data` object before storing it.
        Has access to the `client` if needed to do pre-conditioning.

        Parameters
        ----------
        client : PortalClient
            A PortalClient connected to a server used for storage access
        """
        pass

    def sync(self, client: Optional["PortalClient"] = None) -> "ObjectId":
        """Synchronizes Collection data to the server.

        Data synchronized includes e.g. indices, options, and new molecules.

        Parameters
        ----------
        client : PortalClient, optional
            A PortalClient connected to a server to upload to.

        Returns
        -------
        ObjectId
            The ObjectId of the saved collection.

        """
        class_name = self.__class__.__name__.lower()

        if self._data.name == "":
            raise AttributeError("Collection:save: {} must have a name!".format(class_name))

        if client is None:
            self._check_client()
            client = self._client

        self._pre_save_prep(client)

        # For a collection that is not already on the database
        if self._data.id == self._data.__fields__["id"].default:
            response = client.add_collection(self._data.dict(), overwrite=False, full_return=True)
            if response.meta.success is False:
                raise KeyError(f"Error adding collection: \n{response.meta.error_description}")
            self._data.__dict__["id"] = response.data

        # for a collection that exists on the database
        else:
            response = client.add_collection(self._data.dict(), overwrite=True, full_return=True)
            if response.meta.success is False:
                raise KeyError(f"Error updating collection: \n{response.meta.error_description}")

        return self._data.id

    @abc.abstractmethod
    def compute(
        self, 
        specification: str, 
        subset: Set[str] = None, 
        tag: Optional[str] = None, 
        priority: Optional[str] = None
    ) -> int:
        pass

    def status(
        self,
        specs: Optional[Union[str, List[str]]] = None,
        full: bool = False,
        as_list: bool = False,
        as_df: bool = False,
        status: Optional[Union[str, List[str]]] = None,
    ) -> Union[None, List]:
        """Print or return a status report for all existing compute specifications.

        Parameters
        ----------
        specs : Optional[Union[str, List[str]]]
            If given, only yield status of the listed compute specifications.
        full : bool, optional
            If True, expand to give status per entry.
        as_list: bool, optional
            Return output as a list instead of printing.
        as_df : bool, optional
            Return output as a `pandas` DataFrame instead of printing.
        status : Optional[Union[str, List[str]]], optional
            If not None, only returns results that match the provided statuses.

        Returns
        -------
        Union[None, List]
            Prints output as table to screen; if `aslist=True`,
            returns list of output content instead.

        """
        # TODO: consider instead creating a `status` REST API endpoint
        # no real need for us to populate data objects to get this
        from tabulate import tabulate

        # preprocess inputs
        if specs is None:
            specs = self.list_specifications(description=False)
        elif isinstance(specs, str):
            specs = [specs]

        if isinstance(status, str):
            status = [status.lower()]
        elif isinstance(status, list):
            status = [s.lower() for s in status]

        records = self[specs]

        status_data = pd.DataFrame(records).applymap(lambda x: x.status.value if isinstance(x, RecordBase) else None)

        # apply filters
        if status is not None:
            status_data = status_data[status_data.applymap(lambda x: x in status).any(axis=0)]

        # apply transformations
        if full:
            output = status_data
        else:
            output = status_data.apply(lambda x: x.value_counts())
            output.index.name = "status"

        # give representation
        if not (as_list or as_df):
            print(tabulate(output.reset_index().to_dict("records"), headers="keys"))
        elif as_list:
            return output.reset_index().to_dict("records")
        elif as_df:
            return output

    ## miscellaneous

    @staticmethod
    def _add_molecules_by_dict(client, molecules):

        flat_map_keys = []
        flat_map_mols = []
        for k, v in molecules.items():
            flat_map_keys.append(k)
            flat_map_mols.append(v)

        CHUNK_SIZE = client.query_limit
        mol_ret = []
        for i in range(0, len(flat_map_mols), CHUNK_SIZE):
            mol_ret.extend(client.add_molecules(flat_map_mols[i : i + CHUNK_SIZE]))

        return {k: v for k, v in zip(flat_map_keys, mol_ret)}


class BaseProcedureDataset(Collection):
    class _DataModel(Collection._DataModel):

        records: Dict[str, Any] = {}
        history: Set[str] = set()
        specs: Dict[str, Any] = {}

        class Config(Collection._DataModel.Config):
            pass

    def __init__(self, name: str, client: "PortalClient" = None, **kwargs):
        """Initialize a ProcedureDataset Collection.

        Parameters
        ----------
        name : str
            The name of the Collection object; used to reference the collection on the server.
        client : PortalClient, optional
            A PortalClient connected to a server.
        **kwargs : Dict[str, Any]
            Additional keywords passed to the Collection and the initial data constructor.
            It is up to Collection subclasses to make use of that data.
        """

        if client is None:
            raise KeyError("{self.__class__.__name__} must initialize with a PortalClient.")

        super().__init__(name, client=client, **kwargs)

    def __getitem__(self, spec: Union[List[str], str]):
        if isinstance(spec, list):
            pad = max(map(len, spec))
            return {sp: self._query(sp, pad=pad) for sp in spec}
        else:
            return self._query(spec)

    @abc.abstractmethod
    def _internal_compute_add(self, spec: Any, entry: Any, tag: str, priority: str) -> "ObjectId":
        pass

    def _pre_sync_prep(self, client: "PortalClient") -> None:
        pass

    def _get_index(self):
        return [x.name for x in self._data.records.values()]

    def _add_specification(self, name: str, spec: Any, overwrite=False) -> None:
        """
        Parameters
        ----------
        name : str
            The name of the specification
        spec : Any
            The specification object
        overwrite : bool, optional
            Overwrite existing specification names

        """

        lname = name.lower()
        if (lname in self._data.specs) and (not overwrite):
            raise KeyError(f"{self.__class__.__name__} '{name}' already present, use `overwrite=True` to replace.")

        self._data.specs[lname] = spec
        self.sync()

    def _get_procedure_ids(self, spec: str, sieve: Optional[List[str]] = None) -> Dict[str, "ObjectId"]:
        """Get a mapping of record names to its object ID in the database.

        Parameters
        ----------
        spec : str
            The specification to get mapping for.
        sieve : Optional[List[str]], optional
            List of record names to restrict the mapping to.

        Returns
        -------
        Dict[str, ObjectId]
            A dictionary of identifier to id mappings.

        """

        spec = self.get_specification(spec)

        mapper = {}
        for rec in self._data.records.values():
            if sieve and rec.name not in sieve:
                continue

            try:
                td_id = rec.object_map[spec.name]
                mapper[rec.name] = td_id
            except KeyError:
                pass

        return mapper

    @property
    def specs(self):
        return self.list_specifications()

    @property
    def entry_names(self):
        return self._get_index()

    @property
    def entries(self):
        """A dictionary with entry names as keys and entry content as values."""
        return dict(self._data.records)

    def get_specification(self, name: str) -> Any:
        """Get full parameters for the given named specification.

        Parameters
        ----------
        name : str
            The name of the specification.

        Returns
        -------
        Specification
            The requested specification.

        """
        try:
            return self._data.specs[name.lower()].copy()
        except KeyError:
            raise KeyError(f"Specification '{name}' not found.")

    def list_specifications(self, description=False) -> Union[List[str], Dict[str, str]]:
        """Gives all available specifications.

        Parameters
        ----------
        description : bool, optional
            If True, returns a dictionary with spec names as keys, descriptions as values.

        Returns
        -------
        Union[List[str], Dict[str, str]]
            Known specification names.

        """
        if description:
            return {x.name: x.description for x in self._data.specs.values()}
        else:
            return [x.name for x in self._data.specs.values()]

    def _check_entry_exists(self, name):
        """
        Checks if an entry exists or not.
        """

        if name.lower() in self.data.records:
            raise KeyError(f"Record {name} already in the dataset.")

    def _add_entry(self, name, record, save):
        """
        Adds an entry to the records
        """

        self._check_entry_exists(name)
        self.data.records[name.lower()] = record
        if save:
            self.sync()

    def _get_entry(self, name: str) -> Any:
        """Obtains an entry from the Dataset

        Parameters
        ----------
        name : str
            The record name to pull from.

        Returns
        -------
        Record
            The requested entry.
        """
        try:
            return self.data.records[name.lower()]
        except KeyError:
            raise KeyError(f"Could not find entry name '{name}' in the dataset.")

    def _get_record(self, name: str, specification: str) -> Any:
        """Pulls an individual computational record of the requested name and column.

        Parameters
        ----------
        name : str
            The index name to pull the record of.
        specification : str
            The name of specification to pull the record of.

        Returns
        -------
        Any
            The requested Record

        """
        spec = self.get_specification(specification)
        rec_id = self.get_entry(name).object_map.get(spec.name, None)

        if rec_id is None:
            raise KeyError(f"Could not find a record for ({name}: {specification}).")

        return self._client._query_procedures(id=rec_id)[0]

    def compute(
        self, specification: str, subset: Set[str] = None, tag: Optional[str] = None, priority: Optional[str] = None
    ) -> int:
        """Computes a specification for all entries in the dataset.

        Parameters
        ----------
        specification : str
            The specification name.
        subset : Set[str], optional
            Computes only a subset of the dataset.
        tag : Optional[str], optional
            The queue tag to use when submitting compute requests.
        priority : Optional[str], optional
            The priority of the jobs low, medium, or high.

        Returns
        -------
        int
            The number of submitted computations
        """

        specification = specification.lower()
        spec = self.get_specification(specification)
        if subset:
            subset = set(subset)

        submitted = 0
        for entry in self.data.records.values():
            if (subset is not None) and (entry.name not in subset):
                continue

            if spec.name in entry.object_map:
                continue

            entry.object_map[spec.name] = self._internal_compute_add(spec, entry, tag, priority)
            submitted += 1

        self.data.history.add(specification)

        # Nothing to save
        if submitted:
            self.sync()

        return submitted

    def _query(self, specification: str, series: bool = False, pad: int = 0) -> Union[Dict, pd.Series]:
        """Queries a given specification from the server.

        Parameters
        ----------
        specification : str
            The specification name to query.
        series : bool
            If True, return a `pandas.Series`.
        pad : int
            Spaces to pad spec names in progress output

        Returns
        -------
        Union[Dict, pd.Series]
            Records collected from the server.
        """
        # Try to get the specification, will exception if not found.
        spec = self.get_specification(specification)

        mapper = self._get_procedure_ids(spec.name)
        query_ids = list(mapper.values())

        # Chunk up the queries
        procedures: List[Dict[str, Any]] = []
        for i in tqdm(
            range(0, len(query_ids), self._client.query_limit),
            desc="{} || {} ".format(specification.rjust(pad), self._client.address),
        ):
            chunk_ids = query_ids[i : i + self._client.query_limit]
            procedures.extend(self._client._query_procedures(id=chunk_ids))

        proc_lookup = {x.id: x for x in procedures}

        data = {}
        for name, oid in mapper.items():
            try:
                data[name] = proc_lookup[oid]
            except KeyError:
                data[name] = None

        if series:
            return pd.Series(data)
        else:
            return data