from algebra import API
from api.apiutils import Relation
from enum import Enum
from collections import defaultdict
from collections import OrderedDict
import itertools
from DoD import data_processing_utils as dpu


class FilterType(Enum):
    CELL = 0
    ATTR = 1


class DoD:

    def __init__(self, network, store_client):
        self.api = API(network=network, store_client=store_client)

    def virtual_schema_iterative_search(self, list_attributes: [str], list_samples: [str], debug_enumerate_all_jps=False):
        # Align schema definition and samples
        assert len(list_attributes) == len(list_samples)
        sch_def = {attr: value for attr, value in zip(list_attributes, list_samples)}

        # Obtain sets that fulfill individual filters
        filter_drs = dict()
        filter_id = 0
        for attr in sch_def.keys():
            drs = self.api.search_attribute(attr)
            filter_drs[(attr, FilterType.ATTR, filter_id)] = drs
            filter_id += 1

        for cell in sch_def.values():
            drs = self.api.search_content(cell)
            filter_drs[(cell, FilterType.CELL, filter_id)] = drs
            filter_id += 1

        # We group now into groups that convey multiple filters.
        # Obtain list of tables ordered from more to fewer filters.
        table_fulfilled_filters = defaultdict(list)
        for filter, drs in filter_drs.items():
            drs.set_table_mode()
            # All these tables fulfill the filter above
            for table in drs:
                # table_fulfilled_filters[table].append(filter)
                if filter[1] == FilterType.ATTR:
                    if filter not in table_fulfilled_filters[table]:
                        table_fulfilled_filters[table].append(((filter[0], None), FilterType.ATTR, filter[2]))
                elif filter[1] == FilterType.CELL:
                    columns = [c for c in drs.data]  # copy
                    for c in columns:
                        if c.source_name == table:  # filter in this column
                            if filter not in table_fulfilled_filters[table]:
                                table_fulfilled_filters[table].append(((filter[0], c.field_name), FilterType.CELL, filter[2]))
        # sort by value len -> # fulfilling filters

        # table_fulfilled_filters = {key: list(value) for key, value in table_fulfilled_filters.items()}
        #table_fulfilled_filters = OrderedDict(sorted(table_fulfilled_filters.items(), key=lambda el: len(el[1]), reverse=True))
        table_fulfilled_filters = OrderedDict(
            sorted(table_fulfilled_filters.items(), key=lambda el:
            len({filter_id for _, _, filter_id in el[1]}), reverse=True))  # length of unique filters

        if debug_enumerate_all_jps:
            for el in table_fulfilled_filters.items():
                print(el)
            return

        def eager_candidate_exploration():
            def clear_state():
                candidate_group.clear()
                candidate_group_filters_covered.clear()
            # Eagerly obtain groups of tables that cover as many filters as possible
            not_found = True
            while not_found:
                candidate_group = []
                candidate_group_filters_covered = set()
                for i in range(len(list(table_fulfilled_filters.items()))):
                    table_pivot, filters_pivot = list(table_fulfilled_filters.items())[i]
                    # Eagerly add pivot
                    candidate_group.append(table_pivot)
                    for el in filters_pivot:
                        candidate_group_filters_covered.add(el)
                    # Did it cover all filters?
                    if len(candidate_group_filters_covered) == len(filter_drs.items()):
                        candidate_group = sorted(candidate_group)
                        yield (candidate_group, candidate_group_filters_covered)  # early stop
                        # Cleaning
                        clear_state()
                        continue
                    for j in range(len(list(table_fulfilled_filters.items()))):
                        idx = i + j + 1
                        if idx == len(table_fulfilled_filters.items()):
                            break
                        table, filters = list(table_fulfilled_filters.items())[idx]
                        new_filters = len(set(filters).union(candidate_group_filters_covered)) - len(candidate_group_filters_covered)
                        if new_filters > 0:  # add table only if it adds new filters
                            candidate_group.append(table)
                            for el in filters:
                                candidate_group_filters_covered.add(el)
                                # Did it cover all filters?
                                if len(candidate_group_filters_covered) == len(filter_drs.items()):
                                    candidate_group = sorted(candidate_group)
                                    yield (candidate_group, candidate_group_filters_covered)  # early stop
                                    clear_state()
                                    continue
                    candidate_group = sorted(candidate_group)
                    yield (candidate_group, candidate_group_filters_covered)
                    # Cleaning
                    clear_state()

        # Find ways of joining together each group
        cache_unjoinable_pairs = defaultdict(int)
        for candidate_group, candidate_group_filters_covered in eager_candidate_exploration():
            print("")
            print("Exploring: " + str(candidate_group))
            print("Which covers: " + str(candidate_group_filters_covered))
            num_unique_filters = len({f_id for _, _, f_id in candidate_group_filters_covered})
            print("#Filters: " + str(num_unique_filters))

            if len(candidate_group) == 1:
                print("Finished enumeraing groups")
                cache_unjoinable_pairs = OrderedDict(sorted(cache_unjoinable_pairs.items(),
                                                            key=lambda x: x[1], reverse=True))
                for k, v in cache_unjoinable_pairs.items():
                    print(str(k) + " => " + str(v))
                break

            # Pre-check
            # TODO: with a connected components index we can pre-filter many of those groups without checking
            group_with_all_relations, join_path_groups = self.joinable(candidate_group, cache_unjoinable_pairs)
            if debug_enumerate_all_jps:
                print("Join paths which cover candidate group:")
                for jp in group_with_all_relations:
                    print(jp)
                print("Join graphs which cover candidate group: ")
                for i, group in enumerate(join_path_groups):
                    print("Group: " + str(i))
                    for el in group:
                        print(el)
                continue  # We are just interested in all JPs for all candidate groups

            if len(join_path_groups) == 0:
                print("Group: " + str(candidate_group) + " is Non-Joinable")
                continue

            # We first check if the group_with_all_relations is materializable
            materializable_join_groups = []
            if len(group_with_all_relations) > 0:
                join_paths = self.tx_join_paths_to_pair_hops(group_with_all_relations)
                annotated_join_paths = self.annotate_join_paths_with_filter(join_paths,
                                                                            table_fulfilled_filters,
                                                                            candidate_group)
                # Check JP materialization
                print("Found " + str(len(annotated_join_paths)) + " candidate join paths")
                valid_join_paths = self.verify_candidate_join_paths(annotated_join_paths)
                print("Found " + str(len(valid_join_paths)) + " materializable join paths")
                materializable_join_groups.append(valid_join_paths)

            # in this case no need to check the individual groups
            if len(materializable_join_groups) == 0:
                # We need that at least one JP from each group is materializable
                for join_paths in join_path_groups:
                    join_paths = self.tx_join_paths_to_pair_hops(join_paths)
                    annotated_join_paths = self.annotate_join_paths_with_filter(join_paths, table_fulfilled_filters, candidate_group)

                    # Check JP materialization
                    print("Found " + str(len(annotated_join_paths)) + " candidate join paths")
                    # for jp in annotated_join_paths:
                    #     print(jp)

                    # For each candidate join_path, check whether it can be materialized or not,
                    # then show to user (or the other way around)
                    valid_join_paths = self.verify_candidate_join_paths(annotated_join_paths)

                    print("Found " + str(len(valid_join_paths)) + " materializable join paths")

                    if len(valid_join_paths) > 0:
                        materializable_join_groups.append(valid_join_paths)
                    else:
                        print("Group non-materializable")
                        break
            if len(materializable_join_groups) == 0:
                print("Non materializable groups")
                break

            print("RESULT")
            # print(str(materializable_join_groups))

            clean_jp = []
            for annotated_jp in materializable_join_groups[0]:
                jp = []
                filters = set()
                for filter, l, r in annotated_jp:
                    jp.append((l, r))
                    filters.update(filter)
                clean_jp.append((filters, jp))

            print("Sample JP: ")
            for mjp in clean_jp:
                materialized_virtual_schema = dpu.materialize_join_path(mjp, self)
                yield materialized_virtual_schema



    def virtual_schema_exhaustive_search(self, list_attributes: [str], list_samples: [str]):

        # Align schema definition and samples
        assert len(list_attributes) == len(list_samples)
        sch_def = {attr: value for attr, value in zip(list_attributes, list_samples)}

        # Obtain sets that fulfill individual filters
        filter_drs = dict()
        for attr in sch_def.keys():
            drs = self.api.search_attribute(attr)
            filter_drs[(attr, FilterType.ATTR)] = drs

        for cell in sch_def.values():
            drs = self.api.search_content(cell)
            filter_drs[(cell, FilterType.CELL)] = drs

        # We group now into groups that convey multiple filters.
        # Obtain list of tables ordered from more to fewer filters.
        table_fulfilled_filters = defaultdict(list)
        for filter, drs in filter_drs.items():
            drs.set_table_mode()
            for table in drs:
                table_fulfilled_filters[table].append(filter)
        # sort by value len -> # fulfilling filters
        a = sorted(table_fulfilled_filters.items(), key=lambda el: len(el[1]), reverse=True)
        table_fulfilled_filters = OrderedDict(sorted(table_fulfilled_filters.items(), key=lambda el: len(el[1]), reverse=True))

        # Find all combinations of tables...
        # Set cover problem, but enumerating all candidates, not just the minimum size set that covers the universe
        candidate_groups = set()
        num_tables = len(table_fulfilled_filters)
        while num_tables > 0:
            combinations = itertools.combinations(list(table_fulfilled_filters.keys()), num_tables)
            for combination in combinations:
                candidate_groups.add(frozenset(combination))
            num_tables = num_tables - 1

        # ...and order by coverage of filters
        candidate_group_filters = defaultdict(list)
        for candidate_group in candidate_groups:
            filter_set = set()
            for table in candidate_group:
                for filter_covered_by_table in table_fulfilled_filters[table]:
                    filter_set.add(filter_covered_by_table)
            candidate_group_filters[candidate_group] = list(filter_set)
        candidate_group_filters = OrderedDict(sorted(candidate_group_filters.items(), key=lambda el: len(el[1]), reverse=True))

        # Now do all-pairs join paths for each group, and eliminate groups that do not join (future -> transform first)
        joinable_groups = []
        for candidate_group, filters in candidate_group_filters.items():
            if len(candidate_group) > 1:
                join_paths = self.joinable(candidate_group)
                if join_paths > 0:
                    joinable_groups.append((join_paths, filters))
            else:
                joinable_groups.append((candidate_group, filters))  # join not defined on a single table, so we add it

        return joinable_groups

    def joinable(self, group_tables: [str], cache_unjoinable_pairs: defaultdict(int)):
        """
        Check whether there is join graph that connects the tables in the group. This boils down to check
        whether there is a set of join paths which connect all tables.
        :param group_tables:
        :param cache_unjoinable_pairs: this set contains pairs of tables that do not join with each other
        :return:
        """
        assert len(group_tables) > 1

        # Check first with the cache whether these are unjoinable
        for table1, table2 in itertools.combinations(group_tables, 2):
            if (table1, table2) in cache_unjoinable_pairs.keys() or (table2, table1) in cache_unjoinable_pairs.keys():
                # We count the attempt
                cache_unjoinable_pairs[(table1, table2)] += 1
                cache_unjoinable_pairs[(table2, table1)] += 1
                print(table1 + " unjoinable to: " + table2 + " skipping...")
                return [], []

        # if not the size of group_tables, there won't be unique jps with all tables. that may not be good though
        max_hops = 2

        group_with_all_tables = []

        join_path_groups = []  # store groups, as many as pairs of tables in the group
        for table1, table2 in itertools.combinations(group_tables, 2):
            t1 = self.api.make_drs(table1)
            t2 = self.api.make_drs(table2)
            t1.set_table_mode()
            t2.set_table_mode()
            drs = self.api.paths(t1, t2, Relation.PKFK, max_hops=max_hops)
            paths = drs.paths()  # list of lists
            group = []
            if len(paths) == 0:  # then store this info, these tables do not join
                cache_unjoinable_pairs[(table1, table2)] += 1
                cache_unjoinable_pairs[(table2, table1)] += 1
            for p in paths:
                tables_covered = set(group_tables)
                for hop in p:
                    if hop.source_name in tables_covered:
                        tables_covered.remove(hop.source_name)
                if len(tables_covered) == 0:
                    group_with_all_tables.append(p)  # this path covers all tables in group
                else:
                    group.append(p)
            join_path_groups.append(group)
        # Now verify that it's possible to obtain a join graph from these jps
        if len(group_with_all_tables) == 0:
            for el in join_path_groups:
                if len(el) == 0:
                    return [], []  # no jps covering all tables and empty groups => no join graph
        return group_with_all_tables, join_path_groups

    def format_join_paths(self, join_paths):
        """
        Transform this into something readable
        :param join_paths: [(hit, hit)]
        :return:
        """
        formatted_jps = []
        for jp in join_paths:
            formatted_jp = ""
            for hop in jp:
                hop_str = hop.db_name + "." + hop.source_name + "." + hop.field_name
                if formatted_jp == "":
                    formatted_jp += hop_str
                else:
                    formatted_jp += " -> " + hop_str
            formatted_jps.append(formatted_jp)
        return formatted_jps

    def tx_join_paths_to_pair_hops(self, join_paths):
        """
        1. get join path, 2. annotate with values to check for, then 3. format into [(l,r)]
        :param join_paths:
        :param table_fulfilled_filters:
        :return:
        """
        join_paths_hops = []
        for jp in join_paths:
            jp_hops = []
            pair = []
            for hop in jp:
                pair.append(hop)
                if len(pair) == 2:
                    jp_hops.append(tuple(pair))
                    pair.clear()
                    pair.append(hop)
            # Now remove pairs with pointers within same relation
            jp_hops = [(l, r) for l, r in jp_hops if l.source_name != r.source_name]
            join_paths_hops.append(jp_hops)
        return join_paths_hops

    def annotate_join_paths_with_filter(self, join_paths, table_fulfilled_filters, candidate_group):
        annotated_jps = []
        l = None  # memory for last hop
        r = None
        for jp in join_paths:
            # For each hop
            annotated_jp = []
            for l, r in jp:
                # each filter is a (attr, filter-type)
                # Check if l side is a table in the group or just an intermediary
                if l.source_name in candidate_group:  # it's a table in group, so retrieve filters
                    filters = table_fulfilled_filters[l.source_name]
                else:
                    filters = None  # indicating no need to check filters for intermediary node
                annotated_hop = (filters, l, r)
                annotated_jp.append(annotated_hop)
            annotated_jps.append(annotated_jp)
        # Finally we must check if the very last table was also part of the jp, so we can add the filters for it
        if r.source_name in candidate_group:
            filters = table_fulfilled_filters[r.source_name]
            annotated_hop = (filters, r, None)  # r becomes left and we insert a None to indicate the end
            last_hop = annotated_jps[-1]
            last_hop.append(annotated_hop)
        return annotated_jps

    def verify_candidate_join_paths(self, annotated_join_paths):
        materializable_join_paths = []
        for annotated_join_path in annotated_join_paths:
            valid, filters = self.verify_candidate_join_path(annotated_join_path)
            if valid:
                materializable_join_paths.append(annotated_join_path)
        return materializable_join_paths

    def verify_candidate_join_path(self, annotated_join_path):
        tree_valid_filters = dict()
        x = 0
        for filters, l, r in annotated_join_path:  # for each hop
            l_path = self.api.helper.get_path_nid(l.nid)
            tree_for_level = dict()

            # Before checking for filters, translate carrying values into hook attribute in l
            if len(tree_valid_filters) != 0:  # i.e., not first hop
                x_to_remove = set()
                for x, payload in tree_valid_filters.items():
                    carrying_filters, carrying_values = payload
                    attr = carrying_values[1]
                    if attr == l.field_name:
                        continue  # no need to translate values to hook in this case
                    hook_values = set()
                    for carrying_value in carrying_values[0]:
                        values = dpu.find_key_for(l_path + "/" + l.source_name, l.field_name,
                                                   attr, carrying_value)
                        hook_values.update(values)
                    if len(hook_values) > 0:
                        tree_valid_filters[x] = (carrying_filters, (hook_values, l.field_name))  # update tree
                    else:  # does this even make sense?
                        x_to_remove.add(x)
                for x in x_to_remove:
                    del tree_valid_filters[x]
                if len(tree_valid_filters.items()) == 0:
                    return False, set()

            if filters is not None:
                # sort filters so cell type come first
                filters = sorted(filters, key=lambda x: x[1].value)
                # pre-filter carrying values
                for info, filter_type, filter_id in filters:
                    if filter_type == FilterType.CELL:
                        attribute = info[1]
                        cell_value_specified_by_user = info[0]  # this will always be one (?)
                        path = l_path + "/" + l.source_name
                        keys_l = dpu.find_key_for(path, l.field_name,
                                                 attribute, cell_value_specified_by_user)
                        # Check for the first addition
                        if len(tree_valid_filters.items()) == 0:
                            x += 1
                            tree_for_level[x] = ({(info, filter_type, filter_id)}, (set(keys_l), l.field_name))
                        # Now update carrying_values with the first filter
                        for x, payload in tree_valid_filters.items():
                            carrying_filters, carrying_values = payload
                            ix = carrying_values[0].intersection(set(keys_l))
                            if len(ix) > 0:  # if keeps it valid, create branch
                                carrying_filters.add((info, filter_type, filter_id))
                                x += 1
                                tree_for_level[x] = (carrying_filters, (ix, l.field_name))
                    elif filter_type == FilterType.ATTR:
                        # attr filters work with everyone, so just append
                        for x, payload in tree_for_level.items():
                            carrying_filters, carrying_values = payload
                            carrying_filters.add((info, filter_type, filter_id))
                            tree_for_level[x] = (carrying_filters, carrying_values)
            # Now filter with r
            if r is not None:  # if none, we processed the last step already, so time to check the tree
                r_path = self.api.helper.get_path_nid(r.nid)
                x_to_remove = set()
                for x, payload in tree_for_level.items():
                    carrying_filters, carrying_values = payload
                    values_to_carry = set()
                    for carrying_value in carrying_values[0]:
                        path = r_path + "/" + r.source_name
                        exists = dpu.is_value_in_column(carrying_value, path, r.field_name)
                        if exists:
                            values_to_carry.add(carrying_value)  # this one checks
                    if len(values_to_carry) > 0:
                        # here we update the tree at the current level
                        tree_for_level[x] = (carrying_filters, (values_to_carry, r.field_name))
                    else:
                        x_to_remove.add(x)
                # remove if any
                for x in x_to_remove:
                    del tree_for_level[x]  # no more results here, need to prune
                tree_valid_filters = tree_for_level
                if len(tree_valid_filters.items()) == 0:
                    return False, set()  # early stop
        # Check if the join path was valid, also retrieve the number of filters covered by this JP
        if len(tree_valid_filters.items()) > 0:
            unique_filters = set()
            for k, v in tree_valid_filters.items():
                unique_filters.update(v[0])
            return True, len(unique_filters)
        else:
            return False, set()


def test_e2e(dod, number_jps=5):
    attrs = ["Mit Id", "Krb Name", "Hr Org Unit Title"]
    values = ["968548423", "kimball", "Mechanical Engineering"]

    # attrs = ["Last Name", "Building Name", "Bldg Gross Square Footage", "Department Name"]
    # values = ["Madden", "Ray and Maria Stata Center", "", "Dept of Electrical Engineering & Computer Science"]

    i = 0
    for mjp in dod.virtual_schema_iterative_search(attrs, values, debug_enumerate_all_jps=True):
        print("JP: " + str(i))
        i += 1
        print(mjp.head(2))
        if i > number_jps:
            break


def test_joinable(dod):
    candidate_group = ['Employee_directory.csv', 'Drupal_employee_directory.csv']
    #candidate_group = ['Se_person.csv', 'Employee_directory.csv', 'Drupal_employee_directory.csv']
    #candidate_group = ['Tip_detail.csv', 'Tip_material.csv']
    join_paths = dod.joinable(candidate_group)

    # print("RAW: " + str(len(join_paths)))
    # for el in join_paths:
    #     print(el)

    join_paths = dod.format_join_paths(join_paths)

    print("CLEAN: " + str(len(join_paths)))
    for el in join_paths:
        print(el)


if __name__ == "__main__":
    print("DoD")

    from knowledgerepr import fieldnetwork
    from modelstore.elasticstore import StoreHandler
    # basic test
    path_to_serialized_model = "/Users/ra-mit/development/discovery_proto/models/newmitdwh/"
    store_client = StoreHandler()
    network = fieldnetwork.deserialize_network(path_to_serialized_model)

    dod = DoD(network=network, store_client=store_client)

    test_e2e(dod, number_jps=10)

    # test_joinable(dod)