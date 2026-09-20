# Build driver must create/verify this local tag from the exact image ID below.
# Never overwrite or replace the existing validated Python/Node image.
FROM e-base-validation-git-base:1750198e508ceeabc96bb744de28bce36fe877ab0cd7f5a4a2eb0eff6d710f1f
COPY install_validation_git.py /tmp/e-base-install-validation-git.py
RUN /usr/local/bin/python3 -I /tmp/e-base-install-validation-git.py
