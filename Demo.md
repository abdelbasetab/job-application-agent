
# Run the stable offline Sprint-2 demo
python -m job_agent.main run-pipeline --demo --reset-demo-db --query "Werkstudent KI" --limit 5 --threshold 0.5

# Show generated draft applications
python -m job_agent.main show-applications --demo


# Live- Testen


  python -m job_agent.main run-pipeline --query "Python Berlin" --limit 3 --threshold 0.5
  python -m job_agent.main show-applications
  pytest
  optional: Adzuna/BA Live-Test
