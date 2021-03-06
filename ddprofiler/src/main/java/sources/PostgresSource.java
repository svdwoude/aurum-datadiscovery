package sources;

import java.sql.Connection;
import java.sql.SQLException;
import java.util.List;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import core.Conductor;
import core.SourceType;
import core.config.sources.PostgresSourceConfig;
import core.config.sources.SourceConfig;
import core.tasks.ProfileTask;
import core.tasks.ProfileTaskFactory;
import inputoutput.connectors.DBUtils;

public class PostgresSource implements Source {

    final private Logger LOG = LoggerFactory.getLogger(PostgresSource.class.getName());

    @Override
    public void processSource(SourceConfig config, Conductor c) {
	assert (config instanceof PostgresSourceConfig);

	PostgresSourceConfig postgresConfig = (PostgresSourceConfig) config;

	// TODO: at this point we'll be harnessing metadata from the source

	String ip = postgresConfig.getDb_server_ip();
	String port = new Integer(postgresConfig.getDb_server_port()).toString();
	String db_name = postgresConfig.getDatabase_name();
	String username = postgresConfig.getDb_username();
	String password = postgresConfig.getDb_password();
	String dbschema = "default";

	LOG.info("Conn to DB on: {}:{}/{}", ip, port, db_name);

	// FIXME: remove this enum; simplify this
	Connection dbConn = DBUtils.getDBConnection(SourceType.postgres, ip, port, db_name, username, password);

	List<String> tables = DBUtils.getTablesFromDatabase(dbConn, dbschema);
	try {
	    dbConn.close();
	} catch (SQLException e) {
	    e.printStackTrace();
	}
	for (String relation : tables) {
	    LOG.info("Detected relational table: {}", relation);

	    PostgresSourceConfig relationPostgresSourceConfig = (PostgresSourceConfig) postgresConfig.selfCopy();
	    relationPostgresSourceConfig.setRelationName(relation);

	    ProfileTask pt = ProfileTaskFactory.makePostgresProfileTask(relationPostgresSourceConfig);

	    // // FIXME: Remove type
	    // TaskPackage tp =
	    // TaskPackage.makeDBTaskPackage(postgresConfig.getSourceName(),
	    // DBType.POSTGRESQL, ip, port,
	    // db_name, str, username, password);

	    c.submitTask(pt);
	}

    }

}
