# Contributing Guidelines

Thank you for your interest in contributing to this project. Whether it's a bug
report, new feature, correction, or additional documentation, we greatly value
feedback and contributions from our community.

Please read through this document before submitting any issues or pull requests
to ensure we have all the necessary information to effectively respond to your
bug report or contribution.

## Reporting Bugs/Feature Requests

We welcome you to use the issue tracker to report bugs or suggest features.

When filing an issue, please check existing open, or recently closed, issues to
make sure somebody else hasn't already reported the issue. Please try to include
as much information as you can, such as reproducible steps, the version being
used, and anything unusual about your environment.

## Contributing via Pull Requests

Contributions via pull requests are much appreciated. Before sending us a pull
request, please ensure that:

1. You are working against the latest source on the *main* branch.
2. You check existing open, and recently merged, pull requests to make sure
   someone else hasn't addressed the problem already.
3. You open an issue to discuss any significant work — we would hate for your
   time to be wasted.

To send us a pull request, please:

1. Fork the repository.
2. Modify the source; please focus on the specific change you are contributing.
3. Ensure local checks pass:
   ```bash
   pip install -e '.[dev]'
   ruff check agent lambda_invoker tests sample_workload scripts
   pytest -q
   cfn-lint infra/*.yaml
   checkov -f infra/template.yaml
   ```
   Keep IAM least-privilege, keep container images pinned by digest, and do not
   weaken the blocking image scan (`scripts/scan-image.sh`).
4. Commit to your fork using clear commit messages.
5. Send us a pull request, answering any default questions in the pull request
   interface.
6. Pay attention to any automated CI failures reported in the pull request, and
   stay involved in the conversation.

## Code of Conduct

This project has adopted a Code of Conduct. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Security issue notifications

If you discover a potential security issue in this project we ask that you
notify AWS/Amazon Security via our
[vulnerability reporting page](http://aws.amazon.com/security/vulnerability-reporting/).
Please do **not** create a public GitHub issue.

## Licensing

See the [LICENSE](LICENSE) file for our project's licensing. We will ask you to
confirm the licensing of your contribution.
