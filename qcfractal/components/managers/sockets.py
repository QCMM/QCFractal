from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import and_, update, select
from sqlalchemy.orm import selectinload

from qcfractal.db_socket.helpers import get_query_proj_options, get_count, calculate_limit, get_count_2, get_general
from qcfractal.exceptions import ComputeManagerError
from qcfractal.portal.records import RecordStatusEnum
from qcfractal.portal.managers import ManagerStatusEnum, ManagerName
from qcfractal.portal.metadata_models import QueryMetadata
from .db_models import ComputeManagerLogORM, ComputeManagerORM

if TYPE_CHECKING:
    from sqlalchemy.orm.session import Session
    from qcfractal.db_socket.socket import SQLAlchemySocket
    from typing import List, Iterable, Optional, Sequence, Sequence, Dict, Any, Tuple

    ManagerDict = Dict[str, Any]
    ManagerLogDict = Dict[str, Any]


class ManagerSocket:
    def __init__(self, root_socket: SQLAlchemySocket):
        self.root_socket = root_socket
        self._logger = logging.getLogger(__name__)
        self._manager_limit = root_socket.qcf_config.response_limits.manager
        self._manager_log_limit = root_socket.qcf_config.response_limits.manager_log

    @staticmethod
    def save_snapshot(orm: ComputeManagerORM):
        """
        Saves the statistics of a manager to its log
        """

        log_orm = ComputeManagerLogORM(
            claimed=orm.claimed,
            successes=orm.successes,
            failures=orm.failures,
            rejected=orm.rejected,
            total_worker_walltime=orm.total_worker_walltime,
            total_task_walltime=orm.total_task_walltime,
            active_tasks=orm.active_tasks,
            active_cores=orm.active_cores,
            active_memory=orm.active_memory,
            timestamp=orm.modified_on,
        )  # type: ignore

        orm.log.append(log_orm)

    def activate(
        self,
        name_data: ManagerName,
        manager_version: str,
        qcengine_version: str,
        username: Optional[str],
        programs: Dict[str, Optional[str]],
        tags: List[str],
        *,
        session: Optional[Session] = None,
    ) -> int:
        """
        Activates a new manager on the server
        """

        # Strip out empty tags and programs
        tags = [x.lower() for x in tags if len(x) > 0]
        programs = {k.lower(): v for k, v in programs.items() if len(k) > 0}

        if len(tags) == 0:
            raise ComputeManagerError("Manager does not have any tags assigned. Use '*' to match all tags", True)
        if len(programs) == 0:
            raise ComputeManagerError("Manager does not have any programs available", True)

        tags = list(dict.fromkeys(tags))  # remove duplicates, maintaining order (in python 3.6+)

        manager_orm = ComputeManagerORM(
            name=name_data.fullname,
            cluster=name_data.cluster,
            hostname=name_data.hostname,
            username=username,
            tags=tags,
            status=ManagerStatusEnum.active,
            manager_version=manager_version,
            qcengine_version=qcengine_version,
            programs=programs,
        )  # type: ignore

        with self.root_socket.optional_session(session) as session:
            stmt = select(ComputeManagerORM).where(ComputeManagerORM.name == name_data.fullname)
            count = get_count_2(session, stmt)

            if count > 0:
                self._logger.warning(f"Cannot activate duplicate manager: {name_data.fullname}")
                raise ComputeManagerError("A manager with this name already exists", True)

            session.add(manager_orm)
            session.flush()
            return manager_orm.id

    def update_resource_stats(
        self,
        name: str,
        total_worker_walltime: float,
        total_task_walltime: float,
        active_tasks: int,
        active_cores: int,
        active_memory: float,
        *,
        session: Optional[Session] = None,
    ):

        with self.root_socket.optional_session(session) as session:
            stmt = (
                select(ComputeManagerORM)
                .options(selectinload(ComputeManagerORM.log))
                .where(ComputeManagerORM.name == name)
                .with_for_update(skip_locked=False)
            )
            manager: Optional[ComputeManagerORM] = session.execute(stmt).scalar_one_or_none()

            if manager is None:
                raise ComputeManagerError(
                    f"Cannot update resource stats for manager {name} - does not exist", shutdown=True
                )
            if manager.status != ManagerStatusEnum.active:
                raise ComputeManagerError(
                    f"Cannot update resource stats for manager {name} - is not active", shutdown=True
                )

            manager.total_worker_walltime = total_worker_walltime
            manager.total_task_walltime = (total_task_walltime,)
            manager.active_tasks = active_tasks
            manager.active_cores = active_cores
            manager.active_memory = active_memory
            manager.modified_on = datetime.utcnow()

            self.save_snapshot(manager)

    def deactivate(
        self,
        name: Optional[Iterable[str]] = None,
        modified_before: Optional[datetime] = None,
        *,
        reason: str = "(none given)",
        session: Optional[Session] = None,
    ) -> List[str]:
        """Marks managers as inactive

        If both name and modified_before are specified, managers that match both conditions will be deactivated.

        Parameters
        ----------
        name
            Names of managers to mark as inactive
        modified_before
            Mark all managers that were last modified before this date as inactive
        reason
            A descriptive reason given for deactivation
        session
            An existing SQLAlchemy session to use. If None, one will be created. If an existing session
            is used, it will be flushed before returning from this function.

        Returns
        -------
        :
            A list of manager names that were marked as inactive

        """
        if not name and not modified_before:
            return []

        now = datetime.utcnow()
        query_and = []
        if name:
            query_and.append(ComputeManagerORM.name.in_(name))
        if modified_before:
            query_and.append(ComputeManagerORM.modified_on < modified_before)

        stmt = (
            update(ComputeManagerORM)
            .where(and_(ComputeManagerORM.status == ManagerStatusEnum.active, and_(*query_and)))
            .values(status=ManagerStatusEnum.inactive, modified_on=now)
            .returning(ComputeManagerORM.name)
        )

        with self.root_socket.optional_session(session) as session:
            deactivated_names = session.execute(stmt).fetchall()
            deactivated_names = [x[0] for x in deactivated_names]

            # For the manager, also reset any now-orphaned tasks that belonged to that manager
            for dead_name in deactivated_names:
                incomplete_ids = self.root_socket.records.reset_assigned(manager_name=[dead_name], session=session)
                self._logger.info(
                    f"Deactivated manager {dead_name}. Reason: {reason}. Recycling {len(incomplete_ids)} incomplete tasks."
                )

        return deactivated_names

    def get(
        self,
        name: Sequence[str],
        include: Optional[Sequence[str]] = None,
        exclude: Optional[Sequence[str]] = None,
        missing_ok: bool = False,
        *,
        session: Optional[Session] = None,
    ) -> List[Optional[ManagerDict]]:
        """
        Obtain manager information from specified names frm an existing session

        Names for managers are unique, since they include a UUID.

        The returned manager ORMs will be in order of the given names

        If missing_ok is False, then any manager names that are missing in the database will raise an exception.
        Otherwise, the corresponding entry in the returned list of manager info will be None.

        Parameters
        ----------
        name
            A list or other sequence of manager names
        include
            Which fields of the manager info to return. Default is to return all fields.
        exclude
            Remove these fields from the return. Default is to return all fields.
        missing_ok
           If set to True, then missing managers will be tolerated, and the returned list of
           managers will contain None for the corresponding IDs that were not found.
        session
            An existing SQLAlchemy session to use. If None, one will be created

        Returns
        -------
        :
            Manager information as a dictionary in the same order as the given ids.
            If missing_ok is True, then this list will contain None where the manager was missing.
        """

        if len(name) > self._manager_limit:
            raise RuntimeError(f"Request for {len(name)} managers is over the limit of {self._manager_limit}")

        with self.root_socket.optional_session(session, True) as session:
            return get_general(session, ComputeManagerORM, ComputeManagerORM.name, name, include, exclude, missing_ok)

    def query(
        self,
        manager_id: Optional[Iterable[int]] = None,
        name: Optional[Iterable[str]] = None,
        cluster: Optional[Iterable[str]] = None,
        hostname: Optional[Iterable[str]] = None,
        status: Optional[Iterable[ManagerStatusEnum]] = None,
        modified_before: Optional[datetime] = None,
        modified_after: Optional[datetime] = None,
        include: Optional[Iterable[str]] = None,
        exclude: Optional[Iterable[str]] = None,
        limit: Optional[int] = None,
        skip: int = 0,
        *,
        session: Optional[Session] = None,
    ) -> Tuple[QueryMetadata, List[ManagerDict]]:
        """
        General query of managers in the database

        All search criteria are merged via 'and'. Therefore, records will only
        be found that match all the criteria.

        Parameters
        ----------
        manager_id
            Query for managers its ID
        name
            Query for managers based on manager name
        hostname
            Query for managers based on hostname
        cluster
            Query for managers based on cluster name
        status
            Query for managers based on status (active, inactive)
        modified_before
            Query for managers that were last modified before a specific time
        modified_after
            Query for managers that were last modified before a specific time
        include
            Which fields of the manager to return. Default is to return all fields.
        exclude
            Remove these fields from the return. Default is to return all fields.
        limit
            Limit the number of results. If None, the server limit will be used.
            This limit will not be respected if greater than the configured limit of the server.
        skip
            Skip this many results from the total list of matches. The limit will apply after skipping,
            allowing for pagination.
        session
            An existing SQLAlchemy session to use. If None, one will be created

        Returns
        -------
        :
            Metadata about the results of the query, and a list of manager data that were found in the database.
        """

        limit = calculate_limit(self._manager_limit, limit)

        proj_options = get_query_proj_options(ComputeManagerORM, include, exclude)

        and_query = []
        if manager_id is not None:
            and_query.append(ComputeManagerORM.id.in_(manager_id))
        if name is not None:
            and_query.append(ComputeManagerORM.name.in_(name))
        if hostname is not None:
            and_query.append(ComputeManagerORM.hostname.in_(hostname))
        if cluster is not None:
            and_query.append(ComputeManagerORM.cluster.in_(cluster))
        if status is not None:
            and_query.append(ComputeManagerORM.status.in_(status))
        if modified_before is not None:
            and_query.append(ComputeManagerORM.modified_on < modified_before)
        if modified_after is not None:
            and_query.append(ComputeManagerORM.modified_on > modified_after)

        with self.root_socket.optional_session(session, True) as session:
            query = session.query(ComputeManagerORM).filter(and_(*and_query))
            query = query.options(*proj_options)

            n_found = get_count(query)
            results = query.limit(limit).offset(skip).all()
            result_dicts = [x.dict() for x in results]

        meta = QueryMetadata(n_found=n_found, n_returned=len(result_dicts))  # type: ignore
        return meta, result_dicts