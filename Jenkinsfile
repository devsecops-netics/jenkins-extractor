// Extracción programada de métricas Jenkins -> CSV/JSON (artifacts del build).
// Requisitos:
//  - Credencial "Username with password" id=jenkins-api-extractor (svc-metrics + API token).
//  - python3 + python3-venv (>=3.10) en el nodo que ejecuta.
pipeline {
  agent any   // nodo built-in; si luego agregan agentes: agent { label 'python' }

  options {
    timestamps()
    disableConcurrentBuilds()
    timeout(time: 30, unit: 'MINUTES')
    buildDiscarder(logRotator(numToKeepStr: '60', artifactNumToKeepStr: '60'))
  }

  triggers { cron('H 6 * * *') }   // diario ~06:xx

  parameters {
    string(name: 'LOOKBACK_DAYS', defaultValue: '365', description: 'Ventana de extracción en días')
    string(name: 'JOB_INCLUDE_REGEX', defaultValue: '', description: 'Regex de jobs a incluir (vacío = todos)')
    string(name: 'JOB_EXCLUDE_REGEX', defaultValue: '^metrics-extractor$', description: 'Regex de jobs a excluir')
  }

  environment {
    // Corriendo en el controller (contenedor), localhost evita depender de la Jenkins URL configurada.
    JENKINS_API_URL   = 'http://localhost:8080'
    LOOKBACK_DAYS     = "${params.LOOKBACK_DAYS}"
    JOB_INCLUDE_REGEX = "${params.JOB_INCLUDE_REGEX}"
    JOB_EXCLUDE_REGEX = "${params.JOB_EXCLUDE_REGEX}"
    REPORT_TZ         = 'America/Santiago'
    OUTPUT_DIR        = 'out'
    PIP_DISABLE_PIP_VERSION_CHECK = '1'
  }

  stages {
    stage('Setup') {
      steps {
        sh '''
          python3 --version
          python3 -m venv .venv
          . .venv/bin/activate
          pip install -q -r requirements-dev.txt
        '''
      }
    }

    stage('Test') {
      steps {
        sh '. .venv/bin/activate && python -m pytest -q --junitxml=reports/junit.xml'
      }
      post { always { junit allowEmptyResults: true, testResults: 'reports/junit.xml' } }
    }

    stage('Extract') {
      steps {
        withCredentials([usernamePassword(credentialsId: 'svc-metrics',
                                          usernameVariable: 'JENKINS_API_USER',
                                          passwordVariable: 'JENKINS_API_TOKEN')]) {
          // comillas simples: el token no pasa por interpolación Groovy
          sh '. .venv/bin/activate && rm -rf "$OUTPUT_DIR" && python -m jenkins_extractor'
        }
      }
    }
  }

  post {
    success {
      archiveArtifacts artifacts: 'out/*.csv, out/metadata.json', fingerprint: true
    }
    cleanup { deleteDir() }
  }
}
